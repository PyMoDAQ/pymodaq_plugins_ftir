# -*- coding: utf-8 -*-
"""Simulation of the birefringent (TWINS) Fourier transform spectrometer of CEMES.

Pure numpy, no PyMoDAQ and no Qt: it can be used in a script, a notebook or a test, and it is the "hardware" used by
the simulated plugins ``DAQ_Move_FTIRStageSim``, ``DAQ_1DViewer_FTIRCardSim`` and ``DAQ_0DViewer_FTIRCardSim``.

The setup (see Oriana et al., JOSA A 33, 1415 (2016) and the INSA/CEMES project reports)
--------------------------------------------------------------------------------------------
* The light (polarised at 45° of the optical axes) goes through a fixed birefringent block and a pair of alpha-BBO
  wedges, one of them being moved transversally by a SmarAct linear piezo stage. Moving the wedge by ``x`` changes the
  thickness of birefringent material crossed by the beam by ``e = (x - x0) * tan(apex_angle)``, ``x0`` being the
  stage position where the thickness of the wedges compensates the one of the fixed block (zero delay). The beam
  crosses the moving wedge only on a stage travel equal to the wedge length: outside, the signal vanishes.
* The ordinary and extraordinary waves are then delayed by ``tau = delta_n(lambda) * e / c`` (from ``-tau_max`` to
  ``+tau_max`` over the stage travel), i.e. they get a phase difference ``phi = 2 pi delta_n(lambda) e / lambda``.
* A polarising beam splitter at 45° projects the two waves on two photodiodes (``Monitor +`` and ``Monitor -``)
  that receive the two complementary interferograms::

      I+-(x) = 1/2 * integral S(lambda) [1 +- V cos(phi(lambda, x))] dlambda

  ``V`` is the fringe visibility. A transimpedance amplifier outputs the amplified difference ``G (I+ - I-)``: this
  balanced detection removes the intensity fluctuations of the source, common to both diodes.
* The three voltages are digitised by the acquisition card (MCC 128 on the Raspberry Pi version: 16 bits, +-10 V,
  +-5 V, +-2 V or +-1 V ranges, up to 100 kS/s) while the stage moves at constant speed: the interferogram is recorded
  as a function of time, not directly of position.

The Fourier transform of ``I+ - I-`` against the delay gives back the spectrum ``S``. Because ``delta_n`` depends on
the wavelength (dispersion of alpha-BBO, computed here from its Sellmeier equations), the conversion from stage
position to delay is wavelength dependent: this is why the real setup needs a calibration (with a HeNe laser for
instance), and the simulation reproduces it.

What is (deliberately) not simulated: the spectral response of the photodiodes, the transmission of the optics, the
acceleration/deceleration ramps and the closed loop jitter of the stage, the bandwidth of the amplifier.

Main objects
------------
* :class:`TwinsOptics`: light source + TWINS + balanced detection, ``signals(positions)`` gives the voltages.
* :class:`SimulatedStage`: linear stage moving at constant speed in real time (thread safe).
* :class:`SimulatedAcquisitionCard`: acquisition card sampling the voltages at a given rate while the stage moves.
* :class:`TwinsFTIRBench`: the three above, wired together, and :func:`get_bench` that returns the instance shared by
  all the plugins of a process (the stage plugin and the card plugin must see the same stage).

Units: positions in µm, wavelengths in nm, delays in fs, times in s, signals in V.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

C_NM_PER_FS = 299.792458  # speed of light in nm/fs

CHANNELS = ('monitor_plus', 'monitor_minus', 'diff')
CHANNEL_LABELS = {'monitor_plus': 'Monitor +', 'monitor_minus': 'Monitor -', 'diff': 'Amplified difference'}


# ---------------------------------------------------------------------------------------------------------------------
# Birefringent material
# ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SellmeierBirefringent:
    """Uniaxial crystal described by Sellmeier equations ``n^2 = A + B / (l^2 - C) - D l^2`` (l in µm)"""
    name: str
    ordinary: Tuple[float, float, float, float]
    extraordinary: Tuple[float, float, float, float]

    @staticmethod
    def _index(coeffs, wavelength_nm):
        a, b, c, d = coeffs
        l2 = (np.asarray(wavelength_nm, dtype=float) * 1e-3) ** 2
        return np.sqrt(a + b / (l2 - c) - d * l2)

    def n_o(self, wavelength_nm):
        return self._index(self.ordinary, wavelength_nm)

    def n_e(self, wavelength_nm):
        return self._index(self.extraordinary, wavelength_nm)

    def delta_n(self, wavelength_nm):
        """Birefringence ``n_o - n_e`` (positive for alpha-BBO, a negative uniaxial crystal)"""
        return self.n_o(wavelength_nm) - self.n_e(wavelength_nm)


#: alpha-BBO, Sellmeier coefficients as published by the crystal vendors (valid ~ 190 nm - 3.5 µm),
#: delta_n ~ 0.121 at 633 nm (the project report quotes 0.1225)
ALPHA_BBO = SellmeierBirefringent(name='alpha-BBO',
                                  ordinary=(2.67579, 0.02099, 0.00470, 0.00528),
                                  extraordinary=(2.31197, 0.01184, 0.01607, 0.00400))

MATERIALS = {ALPHA_BBO.name: ALPHA_BBO}


# ---------------------------------------------------------------------------------------------------------------------
# Light sources
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class SpectralBand:
    """Gaussian band of the source spectrum (in wavelength)"""
    center_nm: float
    fwhm_nm: float
    amplitude: float = 1.

    @property
    def sigma_nm(self) -> float:
        return self.fwhm_nm / (2 * np.sqrt(2 * np.log(2)))


@dataclass
class LightSource:
    """A spectrum made of Gaussian bands. ``power`` scales the signal on the photodiodes (arbitrary units -> V)"""
    name: str
    bands: List[SpectralBand]
    power: float = 1.

    def spectrum(self, wavelength_nm) -> np.ndarray:
        """True spectral density S(lambda) (normalised so that its maximum is ``power`` for an isolated band)"""
        wl = np.asarray(wavelength_nm, dtype=float)
        s = np.zeros_like(wl)
        for band in self.bands:
            s += band.amplitude * np.exp(-0.5 * ((wl - band.center_nm) / band.sigma_nm) ** 2)
        return self.power * s

    @property
    def wavelength_range_nm(self) -> Tuple[float, float]:
        low = min(b.center_nm - 4 * b.sigma_nm for b in self.bands)
        high = max(b.center_nm + 4 * b.sigma_nm for b in self.bands)
        return max(low, 1.), high


def source_presets() -> Dict[str, LightSource]:
    """Light sources available in the simulation (the keys are shown in the plugin settings)"""
    return {
        'HeNe laser (632.8 nm)': LightSource('HeNe laser (632.8 nm)', [SpectralBand(632.8, 0.002)]),
        'Sodium doublet (589.0/589.6 nm)': LightSource('Sodium doublet (589.0/589.6 nm)',
                                                       [SpectralBand(588.995, 0.01, 1.),
                                                        SpectralBand(589.592, 0.01, 0.5)]),
        'Laser diode (405 nm)': LightSource('Laser diode (405 nm)', [SpectralBand(405., 1.)]),
        'Green LED (530 nm)': LightSource('Green LED (530 nm)', [SpectralBand(530., 35.)]),
        'Red + green LEDs': LightSource('Red + green LEDs', [SpectralBand(530., 35., 1.),
                                                             SpectralBand(625., 20., 0.7)]),
        'White light (halogen)': LightSource('White light (halogen)', [SpectralBand(650., 300.)]),
    }


DEFAULT_SOURCE = 'HeNe laser (632.8 nm)'


# ---------------------------------------------------------------------------------------------------------------------
# Optics + detection
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class DetectionSettings:
    """Photodiodes, amplifier and noise. All in volts"""
    monitor_gain: float = 2.  # V on each monitor photodiode for a source of power 1 (and no interference)
    diff_gain: float = 4.  # gain of the amplified difference channel, relative to the monitors
    visibility: float = 0.9  # fringe contrast V (alignment, polarisation, spatial coherence...)
    offset_v: float = 0.01  # dark offset of the photodiodes/amplifier
    electronic_noise_v: float = 0.002  # white noise added on each channel (rms)
    intensity_noise: float = 0.01  # relative white fluctuation of the source power (rms), common to both diodes
    intensity_drift: float = 0.05  # relative amplitude of a slow drift of the source power
    drift_period_s: float = 7.3  # period of that drift


class TwinsOptics:
    """Light source + TWINS birefringent delay line + balanced detection

    Parameters
    ----------
    source: LightSource
    apex_angle_deg: float
        apex angle of the wedges (7° on the CEMES setup)
    zero_delay_position_um: float
        stage position where the delay between the two polarisations is zero. It depends on the fixed birefringent
        plate (the first one inserted) and on where the stage is mounted on the setup
    wedge_length_um: float
        length of the moving wedge along the displacement: the beam crosses it only on this length of stage travel
    wedge_center_um: float
        stage position where the beam is at the middle of the moving wedge
    beam_diameter_um: float
        diameter of the beam: the signal vanishes progressively (over this length) when the beam leaves the wedge
    material: SellmeierBirefringent
    detection: DetectionSettings
    seed: int or None
        seed of the random generator (noise), for reproducible simulations
    """

    def __init__(self, source: Optional[LightSource] = None, apex_angle_deg: float = 7.,
                 zero_delay_position_um: float = 0., wedge_length_um: float = 25000., wedge_center_um: float = 0.,
                 beam_diameter_um: float = 1000., material: SellmeierBirefringent = ALPHA_BBO,
                 detection: Optional[DetectionSettings] = None, seed: Optional[int] = None):
        self.source = source if source is not None else source_presets()[DEFAULT_SOURCE]
        self.apex_angle_deg = apex_angle_deg
        self.zero_delay_position_um = zero_delay_position_um
        self.wedge_length_um = wedge_length_um
        self.wedge_center_um = wedge_center_um
        self.beam_diameter_um = beam_diameter_um
        self.material = material
        self.detection = detection if detection is not None else DetectionSettings()
        self.rng = np.random.default_rng(seed)

    # --- geometry / delay -------------------------------------------------------------------------------------------
    def thickness_nm(self, position_um) -> np.ndarray:
        """Difference of birefringent thickness crossed by the beam, relative to the zero delay position (nm)"""
        return (np.asarray(position_um, dtype=float) - self.zero_delay_position_um) * 1e3 * \
            np.tan(np.deg2rad(self.apex_angle_deg))

    @property
    def wedge_range_um(self) -> Tuple[float, float]:
        """Stage positions between which the beam crosses the moving wedge"""
        return (self.wedge_center_um - self.wedge_length_um / 2, self.wedge_center_um + self.wedge_length_um / 2)

    def transmission(self, position_um) -> np.ndarray:
        """Fraction of the beam going through the moving wedge (1 on the wedge, 0 once the beam has left it)"""
        x = np.asarray(position_um, dtype=float)
        low, high = self.wedge_range_um
        edge = max(self.beam_diameter_um / 4, 1e-6)
        return 0.5 * (np.tanh((x - low - self.beam_diameter_um / 2) / edge) -
                      np.tanh((x - high + self.beam_diameter_um / 2) / edge))

    def delay_range_fs(self, wavelength_nm: float = 632.8) -> Tuple[float, float]:
        """Delays reachable while the beam is on the wedge"""
        low, high = self.wedge_range_um
        return float(self.delay_fs(low, wavelength_nm)), float(self.delay_fs(high, wavelength_nm))

    def delay_fs(self, position_um, wavelength_nm: float = 632.8) -> np.ndarray:
        """Phase delay between the two polarisations at a given wavelength (fs)"""
        return self.material.delta_n(wavelength_nm) * self.thickness_nm(position_um) / C_NM_PER_FS

    def fringe_period_um(self, wavelength_nm: float = 632.8) -> float:
        """Stage displacement giving one fringe at this wavelength (µm)"""
        return float(wavelength_nm / (self.material.delta_n(wavelength_nm) *
                                      np.tan(np.deg2rad(self.apex_angle_deg))) * 1e-3)

    # --- interferogram ----------------------------------------------------------------------------------------------
    def _band_grid(self, band: SpectralBand, max_thickness_nm: float) -> Tuple[np.ndarray, np.ndarray]:
        """Wavelength samples and weights to integrate one band, fine enough not to alias at the largest delay"""
        sigma = band.sigma_nm
        span = 8 * sigma
        # phase difference across the band: dphi ~ 2 pi delta_n e span / lambda^2, sample it with ~ 8 points/2pi
        dn = float(self.material.delta_n(band.center_nm))
        n_cycles = dn * max_thickness_nm * span / band.center_nm ** 2
        npts = int(np.clip(8 * n_cycles + 33, 33, 20001))
        wl = np.linspace(band.center_nm - span / 2, band.center_nm + span / 2, npts)
        wl = wl[wl > 1.]
        weights = np.exp(-0.5 * ((wl - band.center_nm) / sigma) ** 2)
        weights *= band.amplitude / weights.sum()
        return wl, weights

    def _coherence_thickness_nm(self, band: SpectralBand) -> float:
        """Thickness beyond which the fringes of a band have vanished (envelope below ~1e-14)"""
        dl = band.sigma_nm
        k_low, k_high = (2 * np.pi * self.material.delta_n(wl) / wl
                         for wl in (max(band.center_nm - dl, 1.), band.center_nm + dl))
        dk_sigma = abs(float(k_high - k_low)) / 2  # spread of the wavevector over one sigma of the band
        return 8 / dk_sigma if dk_sigma > 0 else np.inf

    def interference_term(self, position_um) -> np.ndarray:
        """``integral S(l) cos(phi(l, x)) dl`` normalised by the total power (between -1 and 1)"""
        e = np.atleast_1d(self.thickness_nm(position_um))
        out = np.zeros(e.shape)
        total = 0.
        for band in self.source.bands:
            total += band.amplitude
            # outside of the coherence window the band only adds a constant: skip it (white light is fast then)
            inside = np.abs(e) < self._coherence_thickness_nm(band)
            if not np.any(inside):
                continue
            e_in = e[inside]
            wl, w = self._band_grid(band, float(np.max(np.abs(e_in))))
            k = 2 * np.pi * self.material.delta_n(wl) / wl  # rad / nm of thickness
            contribution = np.empty(e_in.shape)
            chunk = max(1, int(2e6 // wl.size))  # keeps the memory use reasonable (positions x wavelengths)
            for start in range(0, e_in.size, chunk):
                sl = slice(start, start + chunk)
                contribution[sl] = np.cos(np.outer(e_in[sl], k)) @ w
            out[inside] += contribution
        return out / total if total > 0 else out

    def ideal_intensities(self, position_um) -> Tuple[np.ndarray, np.ndarray]:
        """Noise free intensities (V) on the two photodiodes"""
        interf = self.detection.visibility * self.interference_term(position_um)
        p = self.source.power * self.detection.monitor_gain * self.transmission(position_um)
        return p / 2 * (1 + interf), p / 2 * (1 - interf)

    def signals(self, position_um, times_s=None, noise: bool = True) -> Dict[str, np.ndarray]:
        """Voltages of the three channels for the given stage positions (and acquisition times, for the drift)

        Returns a dict with the keys of :data:`CHANNELS`.
        """
        position_um = np.atleast_1d(np.asarray(position_um, dtype=float))
        plus, minus = self.ideal_intensities(position_um)
        det = self.detection
        if noise:
            times_s = np.zeros(position_um.shape) if times_s is None else np.asarray(times_s, dtype=float)
            fluct = 1 + det.intensity_drift * np.sin(2 * np.pi * times_s / det.drift_period_s) + \
                det.intensity_noise * self.rng.standard_normal(position_um.shape)
            plus = plus * fluct
            minus = minus * fluct
        diff = det.diff_gain * (plus - minus)
        out = {'monitor_plus': plus + det.offset_v, 'monitor_minus': minus + det.offset_v, 'diff': diff + det.offset_v}
        if noise:
            for key in out:
                out[key] = out[key] + det.electronic_noise_v * self.rng.standard_normal(position_um.shape)
        return out


# ---------------------------------------------------------------------------------------------------------------------
# Clocks
# ---------------------------------------------------------------------------------------------------------------------
class VirtualClock:
    """A clock that only advances when asked: simulations (tests, notebooks) then run without waiting"""

    def __init__(self, t0: float = 0.):
        self._t = float(t0)
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._t

    def advance(self, dt: float):
        with self._lock:
            self._t += max(0., float(dt))


def _wait(clock: Callable[[], float], duration: float):
    """Wait ``duration`` seconds on ``clock`` (advance it if it is a :class:`VirtualClock`)"""
    if isinstance(clock, VirtualClock):
        clock.advance(duration)
    else:
        end = clock() + duration
        while (remaining := end - clock()) > 0:
            time.sleep(min(remaining, 0.05))


# ---------------------------------------------------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------------------------------------------------
class SimulatedStage:
    """Linear stage moving at constant velocity, in real time. Thread safe.

    The position is computed from the clock: a move started at ``t0`` from ``p0`` towards ``target`` is at
    ``p0 + sign * velocity * (t - t0)`` until it reaches the target. This lets the acquisition card know where the
    stage was at each of its samples, as during a real continuous scan.
    """

    def __init__(self, min_um: float = -20500., max_um: float = 20500., velocity_um_s: float = 1000.,
                 position_um: float = 0., reference_um: float = 0., position_noise_um: float = 0.001,
                 clock: Callable[[], float] = time.monotonic, seed: Optional[int] = None):
        self.min_um = min_um
        self.max_um = max_um
        self._velocity = velocity_um_s
        self.reference_um = reference_um
        self.position_noise_um = position_noise_um
        self.clock = clock
        self._lock = threading.RLock()
        self._rng = np.random.default_rng(seed)
        self._start_pos = float(np.clip(position_um, min_um, max_um))
        self._target = self._start_pos
        self._t0 = self.clock()

    # --- trajectory -------------------------------------------------------------------------------------------------
    def _positions_at(self, t):
        t = np.asarray(t, dtype=float)
        distance = self._target - self._start_pos
        travel = np.clip((t - self._t0) * self._velocity, 0, abs(distance))
        return self._start_pos + np.sign(distance) * travel

    def positions_at(self, times_s) -> np.ndarray:
        """True positions (µm) at the given times of :attr:`clock` (for the past and the planned future)"""
        with self._lock:
            return self._positions_at(times_s)

    def _freeze(self):
        """Restart the trajectory from the current position (before changing it)"""
        now = self.clock()
        self._start_pos = float(self._positions_at(now))
        self._t0 = now

    # --- controller like API ----------------------------------------------------------------------------------------
    @property
    def velocity_um_s(self) -> float:
        return self._velocity

    @velocity_um_s.setter
    def velocity_um_s(self, velocity: float):
        if velocity <= 0:
            raise ValueError('The velocity must be strictly positive')
        with self._lock:
            self._freeze()
            self._velocity = float(velocity)

    def get_position(self) -> float:
        """Position read by the encoder (µm), with a small reading noise"""
        with self._lock:
            pos = float(self._positions_at(self.clock()))
        return pos + self.position_noise_um * float(self._rng.standard_normal())

    def move_abs(self, target_um: float):
        """Start a move (non blocking). The target is clipped to the travel range"""
        with self._lock:
            self._freeze()
            self._target = float(np.clip(target_um, self.min_um, self.max_um))

    def move_rel(self, shift_um: float):
        with self._lock:
            self._freeze()
            self._target = float(np.clip(self._target + shift_um, self.min_um, self.max_um))

    def home(self):
        """Go to the reference mark (non blocking)"""
        self.move_abs(self.reference_um)

    def stop(self):
        with self._lock:
            self._freeze()
            self._target = self._start_pos

    @property
    def target_um(self) -> float:
        return self._target

    def is_moving(self) -> bool:
        with self._lock:
            return abs(float(self._positions_at(self.clock())) - self._target) > 0

    def time_to_target(self) -> float:
        """Remaining duration of the current move (s)"""
        with self._lock:
            return abs(self._target - float(self._positions_at(self.clock()))) / self._velocity


# ---------------------------------------------------------------------------------------------------------------------
# Acquisition card
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class AcquisitionResult:
    times_s: np.ndarray  # time of each sample since the start of the acquisition
    data: Dict[str, np.ndarray]  # voltages, keys from CHANNELS
    positions_um: np.ndarray  # true stage positions at each sample (simulation only: the real card cannot know them)
    start_time: float  # time of the first sample, on the clock of the bench


class SimulatedAcquisitionCard:
    """Analog input card (MCC 128 like): finite acquisitions of ``n_samples`` at ``rate_hz`` on some channels

    ``acquire`` is blocking and lasts ``(n_samples - 1) / rate_hz`` seconds in real time (on a :class:`VirtualClock`
    it advances the clock instead, or with ``realtime=False`` it returns at once), like the real card, so that the
    stage moves during the acquisition. ``abort`` (from another thread) stops it early: the samples not acquired
    are then dropped.
    """
    ranges_v = (10., 5., 2., 1.)
    n_bits = 16
    max_rate_hz = 100_000

    def __init__(self, optics: TwinsOptics, stage: SimulatedStage, input_range_v: float = 10.,
                 realtime: bool = True):
        self.optics = optics
        self.stage = stage
        self.input_range_v = input_range_v
        self.realtime = realtime
        self._abort = threading.Event()

    @property
    def input_range_v(self) -> float:
        return self._range

    @input_range_v.setter
    def input_range_v(self, value: float):
        if value not in self.ranges_v:
            raise ValueError(f'The input range must be one of {self.ranges_v}')
        self._range = float(value)

    def digitize(self, volts: np.ndarray) -> np.ndarray:
        """Clipping to the input range and quantisation on ``n_bits``"""
        lsb = 2 * self._range / 2 ** self.n_bits
        return np.clip(np.round(volts / lsb) * lsb, -self._range, self._range - lsb)

    def abort(self):
        self._abort.set()

    def acquire(self, n_samples: int, rate_hz: float, channels: Sequence[str] = CHANNELS) -> AcquisitionResult:
        if not 0 < rate_hz <= self.max_rate_hz:
            raise ValueError(f'The sampling rate must be in ]0, {self.max_rate_hz}] Hz')
        if n_samples < 1:
            raise ValueError('At least one sample must be acquired')
        unknown = set(channels) - set(CHANNELS)
        if unknown:
            raise ValueError(f'Unknown channels: {unknown}')
        self._abort.clear()
        t0 = self.stage.clock()
        times = t0 + np.arange(n_samples) / rate_hz
        if self.realtime and not isinstance(self.stage.clock, VirtualClock):
            end = times[-1]
            while not self._abort.is_set():
                remaining = end - self.stage.clock()
                if remaining <= 0:
                    break
                self._abort.wait(min(remaining, 0.05))
            times = times[times <= self.stage.clock()] if self._abort.is_set() else times
            if times.size == 0:
                times = np.array([t0])
        elif isinstance(self.stage.clock, VirtualClock):
            self.stage.clock.advance(times[-1] - t0)
        positions = self.stage.positions_at(times)
        signals = self.optics.signals(positions, times)
        data = {ch: self.digitize(signals[ch]) for ch in channels}
        return AcquisitionResult(times_s=times - t0, data=data, positions_um=positions, start_time=t0)


# ---------------------------------------------------------------------------------------------------------------------
# The whole bench
# ---------------------------------------------------------------------------------------------------------------------
class TwinsFTIRBench:
    """Optics, stage and acquisition card of the simulated setup, sharing the same clock"""

    def __init__(self, optics: Optional[TwinsOptics] = None, stage: Optional[SimulatedStage] = None,
                 card: Optional[SimulatedAcquisitionCard] = None):
        self.optics = optics if optics is not None else TwinsOptics()
        self.stage = stage if stage is not None else SimulatedStage()
        self.card = card if card is not None else SimulatedAcquisitionCard(self.optics, self.stage)

    @classmethod
    def from_config(cls, config) -> 'TwinsFTIRBench':
        """Build the bench from the ``simulation`` section of the configuration of the plugin

        ``config`` is a callable as the configuration objects of PyMoDAQ: ``config('simulation', 'stage', 'min_um')``
        """
        def get(*keys, default=None):
            try:
                value = config('simulation', *keys)
            except Exception:
                value = None
            return default if value is None else value

        presets = source_presets()
        source = presets.get(get('source', 'preset', default=DEFAULT_SOURCE), presets[DEFAULT_SOURCE])
        source.power = float(get('source', 'power', default=1.))
        detection = DetectionSettings()
        for name in DetectionSettings.__dataclass_fields__:
            value = get('detection', name)
            if value is not None:
                setattr(detection, name, float(value))
        material = MATERIALS.get(get('twins', 'material', default=ALPHA_BBO.name), ALPHA_BBO)
        optics = TwinsOptics(source=source,
                             apex_angle_deg=float(get('twins', 'apex_angle_deg', default=7.)),
                             zero_delay_position_um=float(get('twins', 'zero_delay_position_um', default=0.)),
                             wedge_length_um=float(get('twins', 'wedge_length_um', default=25000.)),
                             wedge_center_um=float(get('twins', 'wedge_center_um', default=0.)),
                             beam_diameter_um=float(get('twins', 'beam_diameter_um', default=1000.)),
                             material=material, detection=detection)
        stage = SimulatedStage(min_um=float(get('stage', 'min_um', default=-20500.)),
                               max_um=float(get('stage', 'max_um', default=20500.)),
                               velocity_um_s=float(get('stage', 'velocity_um_s', default=1000.)),
                               reference_um=float(get('stage', 'reference_um', default=0.)),
                               position_noise_um=float(get('stage', 'position_noise_um', default=0.001)))
        card = SimulatedAcquisitionCard(optics, stage, input_range_v=float(get('card', 'input_range_v', default=10.)))
        return cls(optics, stage, card)

    def set_source(self, preset: str):
        power = self.optics.source.power
        self.optics.source = source_presets()[preset]
        self.optics.source.power = power

    def ideal_interferogram(self, positions_um) -> np.ndarray:
        """Noise free amplified difference vs stage position (V): handy to check an analysis"""
        plus, minus = self.optics.ideal_intensities(positions_um)
        return self.optics.detection.diff_gain * (plus - minus)

    def scan(self, start_um: float, stop_um: float, rate_hz: float,
             channels: Sequence[str] = CHANNELS) -> AcquisitionResult:
        """What a continuous scan does: go to ``start``, then move to ``stop`` while acquiring (blocking)

        The number of samples is computed from the duration of the move at the current velocity.
        """
        self.stage.move_abs(start_um)
        _wait(self.stage.clock, self.stage.time_to_target())
        duration = abs(stop_um - start_um) / self.stage.velocity_um_s
        n_samples = max(1, int(duration * rate_hz) + 1)
        self.stage.move_abs(stop_um)
        return self.card.acquire(n_samples, rate_hz, channels)


_bench_lock = threading.Lock()
_bench: Optional[TwinsFTIRBench] = None


def get_bench(config=None) -> TwinsFTIRBench:
    """Return the bench shared by all the simulated plugins of this process (created at the first call)"""
    global _bench
    with _bench_lock:
        if _bench is None:
            _bench = TwinsFTIRBench.from_config(config) if config is not None else TwinsFTIRBench()
        return _bench


def reset_bench(bench: Optional[TwinsFTIRBench] = None):
    """Replace (or forget, if None) the shared bench: for tests, or to restart from the configuration"""
    global _bench
    with _bench_lock:
        _bench = bench


# ---------------------------------------------------------------------------------------------------------------------
# Helpers for the analysis (the job of the extension, given here as a reference to check it)
# ---------------------------------------------------------------------------------------------------------------------
def spectrum_from_interferogram(delay_fs: np.ndarray, signal: np.ndarray,
                                apodization: Optional[str] = 'hann') -> Tuple[np.ndarray, np.ndarray]:
    """Reference implementation: spectrum (modulus of the FFT) against wavelength (nm) for a delay axis in fs

    The delay axis must be regularly sampled. The delay to frequency conversion uses a single delta_n, so the
    wavelength axis is only exact at the calibration wavelength (dispersion is ignored).
    """
    delay_fs = np.asarray(delay_fs, dtype=float)
    signal = np.asarray(signal, dtype=float) - np.mean(signal)
    if apodization == 'hann':
        signal = signal * np.hanning(signal.size)
    dt = float(np.mean(np.diff(delay_fs)))
    spec = np.abs(np.fft.rfft(signal))
    freq_per_fs = np.fft.rfftfreq(signal.size, d=abs(dt))  # in 1/fs = PHz
    with np.errstate(divide='ignore'):
        wavelength_nm = np.where(freq_per_fs > 0, C_NM_PER_FS / np.where(freq_per_fs > 0, freq_per_fs, 1), np.inf)
    return wavelength_nm, spec


__all__ = ['C_NM_PER_FS', 'CHANNELS', 'CHANNEL_LABELS', 'SellmeierBirefringent', 'ALPHA_BBO', 'MATERIALS',
           'SpectralBand', 'LightSource', 'source_presets', 'DEFAULT_SOURCE', 'DetectionSettings', 'TwinsOptics',
           'VirtualClock', 'SimulatedStage', 'AcquisitionResult', 'SimulatedAcquisitionCard', 'TwinsFTIRBench', 'get_bench',
           'reset_bench', 'spectrum_from_interferogram']
