"""Tests of the physics and of the timing of the simulated TWINS spectrometer (pure numpy, virtual clock)"""
import numpy as np
import pytest

from pymodaq_plugins_ftir.hardware.twins_simulator import (
    ALPHA_BBO, CHANNELS, DetectionSettings, LightSource, SimulatedAcquisitionCard, SimulatedStage, SpectralBand,
    TwinsFTIRBench, TwinsOptics, VirtualClock, source_presets, spectrum_from_interferogram)

QUIET = DetectionSettings(electronic_noise_v=0., intensity_noise=0., intensity_drift=0., offset_v=0.)


@pytest.fixture
def bench():
    clock = VirtualClock()
    optics = TwinsOptics(detection=DetectionSettings(), seed=0)
    stage = SimulatedStage(velocity_um_s=2000., clock=clock, seed=0)
    return TwinsFTIRBench(optics, stage)


def test_alpha_bbo_birefringence():
    assert ALPHA_BBO.delta_n(632.8) == pytest.approx(0.1225, abs=0.003)  # value quoted in the project report
    assert ALPHA_BBO.delta_n(400.) > ALPHA_BBO.delta_n(800.)  # normal dispersion of the birefringence


def test_delay_is_zero_at_the_zero_delay_position():
    optics = TwinsOptics(zero_delay_position_um=1234.)
    assert optics.delay_fs(1234.) == pytest.approx(0.)
    assert optics.delay_fs(2234.) == pytest.approx(-optics.delay_fs(234.))


def test_hene_fringe_period():
    optics = TwinsOptics(detection=QUIET)
    period = optics.fringe_period_um(632.8)
    x = np.linspace(0, 10 * period, 2001)
    plus, minus = optics.ideal_intensities(x)
    # maxima of Monitor + at every period, complementary channels
    assert plus[0] == pytest.approx(plus[-1], rel=1e-6)
    assert plus[0] > plus[1000 // 10]
    np.testing.assert_allclose(plus + minus, optics.source.power * QUIET.monitor_gain)
    # one delay period of the HeNe = one optical period
    assert optics.delay_fs(period) == pytest.approx(632.8 / 299.792458, rel=1e-6)


def test_white_light_fringes_are_localised_around_zero_delay():
    optics = TwinsOptics(source=source_presets()['White light (halogen)'], detection=QUIET)
    near = optics.interference_term(np.linspace(-5, 5, 101))
    far = optics.interference_term(np.linspace(5000, 5010, 101))
    assert np.max(np.abs(near)) > 0.9
    assert np.max(np.abs(far)) < 1e-3


def test_balanced_detection_removes_intensity_noise():
    detection = DetectionSettings(electronic_noise_v=0., intensity_noise=0.05, intensity_drift=0., offset_v=0.,
                                  visibility=0.)
    optics = TwinsOptics(detection=detection, seed=1)
    out = optics.signals(np.zeros(1000))
    assert np.std(out['monitor_plus']) > 0.01
    assert np.std(out['diff']) == pytest.approx(0., abs=1e-12)


def test_stage_moves_at_constant_velocity():
    clock = VirtualClock()
    stage = SimulatedStage(velocity_um_s=100., clock=clock, position_noise_um=0.)
    stage.move_abs(1000.)
    assert stage.is_moving()
    clock.advance(2.)
    assert stage.get_position() == pytest.approx(200.)
    assert stage.time_to_target() == pytest.approx(8.)
    stage.stop()
    clock.advance(1.)
    assert stage.get_position() == pytest.approx(200.)
    assert not stage.is_moving()


def test_stage_is_limited_to_its_travel_range():
    stage = SimulatedStage(min_um=-10., max_um=10., clock=VirtualClock())
    stage.move_abs(100.)
    assert stage.target_um == 10.


def test_card_digitises_on_16_bits_and_clips():
    card = SimulatedAcquisitionCard(TwinsOptics(), SimulatedStage(clock=VirtualClock()), input_range_v=1.)
    values = card.digitize(np.array([0.123456, 5., -5.]))
    lsb = 2 / 2 ** 16
    assert values[0] == pytest.approx(round(0.123456 / lsb) * lsb)
    assert values[1] < 1. and values[2] == -1.
    with pytest.raises(ValueError):
        card.input_range_v = 3.


def test_acquisition_during_a_move(bench):
    bench.stage.move_abs(2000.)
    result = bench.card.acquire(1001, 1000., CHANNELS)
    assert result.times_s[-1] == pytest.approx(1.)
    assert result.positions_um[0] == pytest.approx(0.)
    assert result.positions_um[-1] == pytest.approx(2000.)
    assert set(result.data) == set(CHANNELS)
    # ~ 2000 / 42.5 fringes on the difference channel: count the zero crossings
    diff = result.data['diff'] - np.mean(result.data['diff'])
    crossings = np.count_nonzero(np.diff(np.sign(diff)) != 0)
    assert crossings == pytest.approx(2 * 2000 / bench.optics.fringe_period_um(), rel=0.1)


def test_scan_gives_back_the_spectrum(bench):
    bench.optics.source = LightSource('test', [SpectralBand(600., 20.)])
    result = bench.scan(-3000., 3000., 5000.)
    delay = bench.optics.delay_fs(result.positions_um, 600.)
    wavelength, spectrum = spectrum_from_interferogram(delay, result.data['diff'])
    visible = (wavelength > 400) & (wavelength < 900)
    assert wavelength[visible][np.argmax(spectrum[visible])] == pytest.approx(600., abs=5.)


def test_bench_from_config():
    values = {('simulation', 'twins', 'apex_angle_deg'): 10., ('simulation', 'stage', 'velocity_um_s'): 5.,
              ('simulation', 'source', 'preset'): 'Green LED (530 nm)'}
    bench = TwinsFTIRBench.from_config(lambda *keys: values.get(keys))
    assert bench.optics.apex_angle_deg == 10.
    assert bench.stage.velocity_um_s == 5.
    assert bench.optics.source.bands[0].center_nm == 530.
