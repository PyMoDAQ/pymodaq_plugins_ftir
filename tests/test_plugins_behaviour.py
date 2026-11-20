"""Behaviour of the simulated plugins, driven as PyMoDAQ does (``pymodaq.utils.plugin_testing``), without GUI"""
import numpy as np
import pytest

from pymodaq.utils.data import DataActuator
from pymodaq.utils.plugin_testing import (make_actuator, make_detector, move_abs_and_wait, move_rel_and_wait,
                                          move_home_and_wait, grab_and_wait, assert_units)

from pymodaq_plugins_ftir.hardware.twins_simulator import SimulatedStage, TwinsFTIRBench, TwinsOptics, reset_bench
from pymodaq_plugins_ftir.daq_move_plugins.daq_move_FTIRStageSim import DAQ_Move_FTIRStageSim
from pymodaq_plugins_ftir.daq_viewer_plugins.plugins_1D.daq_1Dviewer_FTIRCardSim import DAQ_1DViewer_FTIRCardSim
from pymodaq_plugins_ftir.daq_viewer_plugins.plugins_0D.daq_0Dviewer_FTIRCardSim import DAQ_0DViewer_FTIRCardSim


def set_setting(plugin, *path_and_value):
    """Change a setting as the user would: PyMoDAQ then calls commit_settings in the plugin thread"""
    *path, value = path_and_value
    param = plugin.settings.child(*path)
    param.setValue(value)
    plugin.commit_settings(param)


@pytest.fixture(autouse=True)
def bench():
    """A fresh shared bench for each test (the plugins take it with get_bench)"""
    bench = TwinsFTIRBench(TwinsOptics(seed=0), SimulatedStage(seed=0))
    reset_bench(bench)
    yield bench
    reset_bench(None)


@pytest.fixture
def stage(qapp):
    plugin = make_actuator(DAQ_Move_FTIRStageSim, velocity=20.)  # mm/s, fast moves for the tests
    assert plugin.initialized
    yield plugin
    plugin.close()


@pytest.fixture
def card(qapp):
    plugin = make_detector(DAQ_1DViewer_FTIRCardSim, rate=10000., n_samples=1000)
    assert plugin.initialized
    yield plugin
    plugin.close()


class TestStage:
    def test_uses_the_shared_bench(self, stage, bench):
        assert stage.controller is bench.stage
        assert bench.stage.velocity_um_s == pytest.approx(20000.)

    def test_units(self, stage):
        assert stage.get_actuator_value().units == 'mm'

    def test_move_abs_takes_time(self, stage, bench):
        bench.stage.position_noise_um = 0.
        pos = move_abs_and_wait(stage, 1.)
        assert pos.value('mm') == pytest.approx(1., abs=1e-4)
        assert bench.stage.get_position() == pytest.approx(1000., abs=0.1)

    def test_move_rel_and_other_units(self, stage):
        move_abs_and_wait(stage, 0.5)
        pos = move_rel_and_wait(stage, DataActuator(data=250., units='µm').units_as('mm', inplace=False))
        assert pos.value('mm') == pytest.approx(0.75, abs=1e-4)

    def test_move_home(self, stage):
        move_abs_and_wait(stage, -0.3)
        pos = move_home_and_wait(stage)
        assert pos.value('mm') == pytest.approx(0., abs=1e-4)

    def test_stop_motion(self, stage, bench):
        set_setting(stage, 'velocity', 1.)
        stage.move_abs(DataActuator(data=10., units='mm'))
        stage.stop_motion()
        assert not bench.stage.is_moving()
        assert abs(bench.stage.get_position()) < 1000.

    def test_delay_is_displayed(self, stage, bench):
        move_abs_and_wait(stage, 1.)
        stage.get_actuator_value()
        assert stage.settings['twins', 'delay_fs'] == pytest.approx(float(bench.optics.delay_fs(1000.)), rel=1e-3)


    def test_twins_geometry_settings(self, stage, bench):
        set_setting(stage, 'twins', 'apex_angle', 10.)
        set_setting(stage, 'twins', 'wedge_length', 20.)
        set_setting(stage, 'twins', 'wedge_center', 1.)
        set_setting(stage, 'twins', 'zero_delay', -2.)
        optics = bench.optics
        assert optics.apex_angle_deg == 10.
        assert optics.wedge_range_um == (-9000., 11000.)
        assert optics.zero_delay_position_um == -2000.
        assert stage.settings['twins', 'fringe_period'] == pytest.approx(optics.fringe_period_um(632.8))
        low, high = optics.delay_range_fs(632.8)
        assert stage.settings['twins', 'delay_range'] == f'{low:.0f} to {high:.0f}'


class TestCard:
    def test_grab_1d(self, card):
        dte = grab_and_wait(card)
        assert [dwa.name for dwa in dte] == ['Monitor diodes', 'Amplified difference']
        assert dte[0].shape == (1000,) and len(dte[0]) == 2
        assert_units(dte, 'V')
        assert dte[0].axes[0].units == 's'

    def test_channels_selection_and_positions(self, card):
        set_setting(card, 'channels', 'monitor_plus', False)
        set_setting(card, 'channels', 'monitor_minus', False)
        set_setting(card, 'export_positions', True)
        dte = grab_and_wait(card)
        assert [dwa.name for dwa in dte] == ['Amplified difference', 'Stage position']
        assert dte[1].units == 'µm'

    def test_change_source(self, card, bench):
        set_setting(card, 'simulation', 'source', 'Green LED (530 nm)')
        assert bench.optics.source.bands[0].center_nm == 530.

    def test_interferogram_during_a_scan(self, qapp, stage, card, bench):
        """What the extension will do: go to the start, start the move to the end and grab meanwhile"""
        move_abs_and_wait(stage, -0.5)
        set_setting(stage, 'velocity', 1.)  # 1 mm/s, 1000 samples at 10 kHz = 0.1 mm of travel
        set_setting(card, 'export_positions', True)
        stage.move_abs(DataActuator(data=0.5, units='mm'))
        dte = grab_and_wait(card)
        positions = dte.get_data_from_name('Stage position')[0]
        assert positions[-1] - positions[0] == pytest.approx(100., rel=0.2)
        diff = dte.get_data_from_name('Amplified difference')[0]
        assert np.ptp(diff) > 5.  # fringes of the HeNe laser: several volts peak to peak
        stage.stop_motion()

    def test_0d_mean(self, qapp):
        plugin = make_detector(DAQ_0DViewer_FTIRCardSim)
        dte = grab_and_wait(plugin)
        assert dte[0].dim.name == 'Data0D'
        assert dte[0].shape == (1,) and len(dte[0]) == 2
        plugin.close()
