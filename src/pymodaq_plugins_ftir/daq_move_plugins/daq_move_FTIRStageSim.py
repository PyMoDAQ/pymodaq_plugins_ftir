from typing import List, Union

from qtpy.QtCore import QThread

from pymodaq.control_modules.move_utility_classes import (DAQ_Move_base, comon_parameters_fun, main,
                                                          DataActuatorType, DataActuator)
from pymodaq.control_modules.daq_move_ui.utils import UiType
from pymodaq_utils.utils import ThreadCommand
from pymodaq_gui.parameter import Parameter

from pymodaq_plugins_ftir.utils import get_config
from pymodaq_plugins_ftir.hardware.twins_simulator import SimulatedStage, TwinsFTIRBench, get_bench

UM_PER_MM = 1000.  # the simulated stage works in µm, the plugin in mm (its axis unit)


class DAQ_Move_FTIRStageSim(DAQ_Move_base):
    """Simulated delay stage of the TWINS Fourier transform spectrometer (SmarAct SLC linear piezo stage)

    No hardware: the stage is the one of the simulated bench of ``hardware/twins_simulator.py``, shared with the
    simulated acquisition card (``DAQ_1DViewer_FTIRCardSim`` / ``DAQ_0DViewer_FTIRCardSim``) so that the card measures
    the interferogram at the position of this stage. The stage moves at constant velocity in real time: a move is not
    instantaneous, and an acquisition started during a move records the fringes passing by, as on the real setup.

    Positions are in mm, as for ``DAQ_Move_SmarActSCUAscii`` (pymodaq_plugins_smaract) that drives the real stage, so
    that one plugin can replace the other in a Dashboard. The velocity, the travel range and the zero delay position
    come from the ``simulation`` section of the configuration of the package (``config_ftir.toml``, in µm there) and
    can be changed in the settings. One fringe of a HeNe laser is ~ 0.043 mm of stage travel (7° wedges).

    Tested with PyMoDAQ 5.3.12, Python 3.13, Linux, against the simulator only (there is no hardware behind it).
    """
    is_multiaxes = False
    _axis_names: Union[List[str], dict] = ['Delay']
    _controller_units: Union[str, List[str]] = 'mm'
    _epsilons: Union[float, List[float]] = 0.0001
    data_actuator_type = DataActuatorType.DataActuator
    ui_type = UiType.NONE
    has_encoder = True

    params = [
        {'title': 'Velocity (mm/s):', 'name': 'velocity', 'type': 'float',
         'value': get_config('simulation', 'stage', 'velocity_um_s', default=1000.) / 1000, 'min': 0.0001,
         'max': 50.},
        {'title': 'Travel range:', 'name': 'travel', 'type': 'group', 'children': [
            {'title': 'Min (mm):', 'name': 'min', 'type': 'float', 'readonly': True,
             'value': get_config('simulation', 'stage', 'min_um', default=-20500.) / 1000},
            {'title': 'Max (mm):', 'name': 'max', 'type': 'float', 'readonly': True,
             'value': get_config('simulation', 'stage', 'max_um', default=20500.) / 1000},
        ]},
        {'title': 'Zero delay position (mm):', 'name': 'zero_delay', 'type': 'float',
         'value': get_config('simulation', 'twins', 'zero_delay_position_um', default=0.) / 1000,
         'tip': 'Stage position where the two polarisations are not delayed (simulation parameter)'},
        {'title': 'Delay at 632.8 nm (fs):', 'name': 'delay_fs', 'type': 'float', 'value': 0., 'readonly': True,
         'tip': 'Delay corresponding to the current position (true value, given by the simulation)'},
    ] + comon_parameters_fun(is_multiaxes, axis_names=_axis_names, epsilon=_epsilons)

    def ini_attributes(self):
        self.controller: SimulatedStage = None
        self.bench: TwinsFTIRBench = None

    def ini_stage(self, controller=None):
        """Get the stage of the shared simulated bench (master) or the given one (slave)"""
        if self.is_master:
            self.bench = get_bench(lambda *keys: get_config(*keys))
            self.controller = self.bench.stage
        else:
            self.controller = controller
            self.bench = get_bench()
        self.controller.velocity_um_s = self.settings['velocity'] * UM_PER_MM
        self.settings.child('travel', 'min').setValue(self.controller.min_um / UM_PER_MM)
        self.settings.child('travel', 'max').setValue(self.controller.max_um / UM_PER_MM)
        self.bench.optics.zero_delay_position_um = self.settings['zero_delay'] * UM_PER_MM
        self._update_timeout()
        return 'Simulated TWINS delay stage ready', True

    def _update_timeout(self):
        """A full travel at low speed can take longer than the default polling timeout of PyMoDAQ"""
        full_travel_s = (self.controller.max_um - self.controller.min_um) / self.controller.velocity_um_s
        if self.settings['timeout'] < full_travel_s + 5:
            self.settings.child('timeout').setValue(int(full_travel_s + 5))

    def close(self):
        if self.is_master and self.controller is not None:
            self.controller.stop()

    def get_actuator_value(self) -> DataActuator:
        position_um = self.controller.get_position()
        self.settings.child('delay_fs').setValue(float(self.bench.optics.delay_fs(position_um)))
        pos = DataActuator(data=position_um / UM_PER_MM, units=self.axis_unit)
        return self.get_position_with_scaling(pos)

    def move_abs(self, value: DataActuator):
        value = self.check_bound(value)
        self.target_value = value
        value = self.set_position_with_scaling(value)
        self.controller.move_abs(value.value(self.axis_unit) * UM_PER_MM)

    def move_rel(self, value: DataActuator):
        value = self.check_bound(self.current_value + value) - self.current_value
        self.target_value = value + self.current_value
        value = self.set_position_relative_with_scaling(value)
        self.controller.move_rel(value.value(self.axis_unit) * UM_PER_MM)

    def move_home(self):
        """Go to the reference mark. Blocking (as the referencing of the real stage), then calls move_done"""
        self.controller.home()
        self.emit_status(ThreadCommand('Update_Status', ['Moving to the reference mark']))
        while self.controller.is_moving():
            QThread.msleep(int(min(50, 1000 * self.controller.time_to_target()) + 1))
        self.move_done()

    def stop_motion(self):
        self.controller.stop()
        self.move_done()

    def commit_settings(self, param: Parameter):
        if param.name() == 'velocity':
            self.controller.velocity_um_s = param.value() * UM_PER_MM
            self._update_timeout()
        elif param.name() == 'zero_delay':
            self.bench.optics.zero_delay_position_um = param.value() * UM_PER_MM


if __name__ == '__main__':
    main(__file__)
