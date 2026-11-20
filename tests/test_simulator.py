"""Tests of the physics and of the timing of the simulated TWINS spectrometer (pure numpy, virtual clock)"""
import numpy as np
import pytest

from pymodaq_plugins_ftir.hardware.twins.simulator import (
    ALPHA_BBO, CHANNELS, DetectionSettings, LightSource, SimulatedAcquisitionCard, SimulatedStage, SpectralBand,
    TwinsFTIRBench, TwinsOptics, VirtualClock, source_presets, spectrum_from_interferogram,
    spectrum_from_interferogram_dispersive)

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
    # ~ 2000 / fringe period (~ 19.5 µm) fringes on the difference channel: count the zero crossings
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


def test_signal_vanishes_outside_of_the_wedge():
    optics = TwinsOptics(detection=QUIET, wedge_length_um=10000., wedge_center_um=2000., beam_diameter_um=1000.)
    assert optics.wedge_range_um == (-3000., 7000.)
    plus, minus = optics.ideal_intensities(np.array([2000., -4000., 8000.]))
    total = plus + minus
    assert total[0] == pytest.approx(optics.source.power * QUIET.monitor_gain, rel=1e-6)
    assert total[1] < 1e-4 and total[2] < 1e-4
    low, high = optics.delay_range_fs()
    assert low == pytest.approx(float(optics.delay_fs(-3000.))) and high > 0


@pytest.mark.parametrize('wavelength', [450., 633., 1000.])
def test_dispersive_analysis_corrects_the_birefringence_dispersion(wavelength):
    optics = TwinsOptics(source=LightSource('line', [SpectralBand(wavelength, 1.)]), detection=QUIET,
                         apex_angle_deg=15., wedge_length_um=25000.)
    x = np.linspace(-12500, 12500, 2 ** 16)
    signal = optics.signals(x, noise=False)['diff']
    wl, spectrum = spectrum_from_interferogram_dispersive(optics.thickness_nm(x), signal)
    assert wl[np.argmax(spectrum)] == pytest.approx(wavelength, abs=1.)
    # the delay calibrated at a single wavelength (constant delta_n) shifts the lines: -4 % at 450 nm, +3 % at 1000 nm
    wl_c, spectrum_c = spectrum_from_interferogram(optics.delay_fs(x, 632.8), signal)
    selection = (wl_c > 300) & (wl_c < 1500)
    shift = wl_c[selection][np.argmax(spectrum_c[selection])] - wavelength
    assert abs(shift) > 10 if wavelength != 633. else abs(shift) < 1.


def _line_interferogram(wavelength):
    optics = TwinsOptics(source=LightSource('line', [SpectralBand(wavelength, 1.)]), detection=QUIET,
                         apex_angle_deg=15., wedge_length_um=25000.)
    x = np.linspace(-12500, 12500, 2 ** 16)
    return optics.thickness_nm(x), optics.signals(x, noise=False)['diff']


def _peak(calibration, e, signal):
    wl, spectrum = calibration.spectrum(e, signal)
    return wl[np.argmax(spectrum)]


def test_calibration_factory():
    from pymodaq_plugins_ftir.hardware.twins import calibrations  # noqa: F401 (registers all the calibrations)
    from pymodaq_plugins_ftir.hardware.twins.calibration_factory import CalibrationFactory
    from pymodaq_plugins_ftir.hardware.twins.calibrations.polynomial import PolynomialCalibration
    from pymodaq_plugins_ftir.hardware.twins.calibrations.sellmeier import SellmeierCalibration
    assert set(CalibrationFactory.keys()) >= {'Single point', 'Sellmeier', 'Polynomial'}
    assert isinstance(CalibrationFactory.create('Sellmeier'), SellmeierCalibration)
    with pytest.raises(ValueError):
        CalibrationFactory.create('unknown')
    # a polynomial fitted on a few "known lines" reproduces the Sellmeier law between them
    lines = np.array([400., 500., 633., 800., 1000.])
    poly = PolynomialCalibration.fit(lines, ALPHA_BBO.delta_n(lines), order=3)
    assert poly.delta_n(700.) == pytest.approx(float(ALPHA_BBO.delta_n(700.)), abs=2e-4)


def test_new_calibrations_are_registered_with_a_decorator():
    from pymodaq_plugins_ftir.hardware.twins.calibration_factory import CalibrationBase, CalibrationFactory

    @CalibrationFactory.register()
    class Constant(CalibrationBase):
        usual_name = 'Test constant'

        def __init__(self, value=0.1):
            self.value = value

        def delta_n(self, wavelength_nm):
            return np.full(np.shape(wavelength_nm), self.value)

    try:
        assert CalibrationFactory.create('Test constant', value=0.12).delta_n(500.) == pytest.approx(0.12)
    finally:
        CalibrationFactory._builders.pop('Test constant')


def test_materials_are_in_their_own_module():
    from pymodaq_plugins_ftir.hardware.twins.materials import ALPHA_BBO as alpha_bbo, MATERIALS, register_material
    assert MATERIALS['alpha-BBO'] is alpha_bbo


@pytest.mark.parametrize('wavelength', [450., 633., 1000.])
def test_calibrations_recover_a_line(wavelength):
    from pymodaq_plugins_ftir.hardware.twins import calibrations  # registers all the calibrations
    from pymodaq_plugins_ftir.hardware.twins.calibration_factory import CalibrationFactory
    from pymodaq_plugins_ftir.hardware.twins.calibrations.polynomial import PolynomialCalibration
    e, signal = _line_interferogram(wavelength)
    assert _peak(CalibrationFactory.create('Sellmeier'), e, signal) == pytest.approx(wavelength, abs=1.)
    lines = np.linspace(350., 1100., 6)
    poly = PolynomialCalibration.fit(lines, ALPHA_BBO.delta_n(lines), order=4)
    assert _peak(poly, e, signal) == pytest.approx(wavelength, abs=2.)
    single = _peak(CalibrationFactory.create('Single point', wavelength_nm=632.8), e, signal)
    assert (abs(single - wavelength) > 10) if wavelength != 633. else abs(single - wavelength) < 1.
