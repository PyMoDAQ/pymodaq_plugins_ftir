from typing import List, Union

from qtpy.QtCore import QThread

from pymodaq.control_modules.move_utility_classes import (DAQ_Move_base, comon_parameters_fun, main,
                                                          DataActuatorType, DataActuator)
from pymodaq.control_modules.daq_move_ui.utils import UiType
from pymodaq_utils.utils import ThreadCommand
from pymodaq_gui.parameter import Parameter

from pymodaq_data import Q_
from pymodaq_plugins_ftir.utils import get_config, config_quantity, q_from_param
from pymodaq_plugins_ftir.hardware.twins_simulator import SimulatedStage, TwinsFTIRBench, get_bench


class DAQ_Move_FTIRStageSim(DAQ_Move_base):
    """Simulated delay stage of the TWINS Fourier transform spectrometer (SmarAct SLC linear piezo stage)

    No hardware: the stage is the one of the simulated bench of ``hardware/twins_simulator.py``, shared with the
    simulated acquisition card (``DAQ_1DViewer_FTIRCardSim`` / ``DAQ_0DViewer_FTIRCardSim``) so that the card measures
    the interferogram at the position of this stage. The stage moves at constant velocity in real time: a move is not
    instantaneous, and an acquisition started during a move records the fringes passing by, as on the real setup.

    Positions are in mm, as for ``DAQ_Move_SmarActSCUAscii`` (pymodaq_plugins_smaract) that drives the real stage, so
    that one plugin can replace the other in a Dashboard. The velocity, the travel range and the zero delay position
    come from the ``simulation`` section of the configuration of the package (``config_ftir.toml``, in µm there) and
    can be changed in the settings, as the geometry of the TWINS (``TWINS (simulation)`` group: apex angle and
    length of the wedges, positions of the wedge centre and of the zero delay). One fringe of a HeNe laser is
    ~ 0.020 mm of stage travel (15° wedges).

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
        {'title': 'Velocity:', 'name': 'velocity', 'type': 'float', 'suffix': 'mm/s', 'siPrefix': False,
         'value': config_quantity('simulation', 'stage', 'velocity_um_s', stored='µm/s', unit='mm/s', default=1000.).magnitude,
         'min': 0.0001, 'max': 50.},
        {'title': 'Travel range:', 'name': 'travel', 'type': 'group', 'children': [
            {'title': 'Min:', 'name': 'min', 'type': 'float', 'suffix': 'mm', 'readonly': True,
             'value': config_quantity('simulation', 'stage', 'min_um', unit='mm', default=-20500.).magnitude},
            {'title': 'Max:', 'name': 'max', 'type': 'float', 'suffix': 'mm', 'readonly': True,
             'value': config_quantity('simulation', 'stage', 'max_um', unit='mm', default=20500.).magnitude},
        ]},
        {'title': 'TWINS (simulation):', 'name': 'twins', 'type': 'group', 'children': [
            {'title': 'Wedge apex angle:', 'name': 'apex_angle', 'type': 'float', 'suffix': '°',
             'value': get_config('simulation', 'twins', 'apex_angle_deg', default=15.), 'min': 0.01, 'max': 45.},
            {'title': 'Wedge length:', 'name': 'wedge_length', 'type': 'float', 'suffix': 'mm',
             'value': config_quantity('simulation', 'twins', 'wedge_length_um', unit='mm', default=25000.).magnitude,
             'min': 0.1,
             'tip': 'Length of the moving wedge along the displacement: the beam crosses it on this travel only'},
            {'title': 'Wedge centre position:', 'name': 'wedge_center', 'type': 'float', 'suffix': 'mm',
             'value': config_quantity('simulation', 'twins', 'wedge_center_um', unit='mm', default=0.).magnitude,
             'tip': 'Stage position where the beam is at the middle of the moving wedge'},
            {'title': 'Zero delay position:', 'name': 'zero_delay', 'type': 'float', 'suffix': 'mm',
             'value': config_quantity('simulation', 'twins', 'zero_delay_position_um', unit='mm',
                                      default=0.).magnitude,
             'tip': 'Stage position where the two polarisations are not delayed: depends on the fixed plate and on '
                    'the mounting of the stage on the setup'},
            {'title': 'Fringe period at 632.8 nm:', 'name': 'fringe_period', 'type': 'float', 'suffix': 'µm',
             'value': 0., 'readonly': True},
            {'title': 'Delay range at 632.8 nm (fs):', 'name': 'delay_range', 'type': 'str', 'value': '',
             'readonly': True, 'tip': 'Delays reachable while the beam is on the moving wedge'},
            {'title': 'Delay at 632.8 nm:', 'name': 'delay_fs', 'type': 'float', 'suffix': 'fs', 'value': 0.,
             'readonly': True, 'tip': 'Delay of the current position (true value, given by the simulation)'},
        ]},
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
        self.controller.velocity_um_s = q_from_param(self.settings.child('velocity')).to('µm/s').magnitude
        self.settings.child('travel', 'min').setValue(Q_(self.controller.min_um, 'µm').to('mm').magnitude)
        self.settings.child('travel', 'max').setValue(Q_(self.controller.max_um, 'µm').to('mm').magnitude)
        for name in self.TWINS_ATTRIBUTES:
            self._apply_twins(name, self.settings.child('twins', name))
        self._update_timeout()
        return 'Simulated TWINS delay stage ready', True

    #: setting name -> (attribute of TwinsOptics, unit of that attribute)
    TWINS_ATTRIBUTES = {'apex_angle': ('apex_angle_deg', '°'), 'wedge_length': ('wedge_length_um', 'µm'),
                        'wedge_center': ('wedge_center_um', 'µm'),
                        'zero_delay': ('zero_delay_position_um', 'µm')}

    def _apply_twins(self, name: str, param: Parameter):
        attribute, unit = self.TWINS_ATTRIBUTES[name]
        optics = self.bench.optics
        setattr(optics, attribute, q_from_param(param).to(unit).magnitude)
        self.settings.child('twins', 'fringe_period').setValue(optics.fringe_period_um(632.8))
        low, high = optics.delay_range_fs(632.8)
        self.settings.child('twins', 'delay_range').setValue(f'{low:.0f} to {high:.0f}')

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
        self.settings.child('twins', 'delay_fs').setValue(float(self.bench.optics.delay_fs(position_um)))
        pos = DataActuator(data=Q_(position_um, 'µm').to(self.axis_unit).magnitude, units=self.axis_unit)
        return self.get_position_with_scaling(pos)

    def move_abs(self, value: DataActuator):
        value = self.check_bound(value)
        self.target_value = value
        value = self.set_position_with_scaling(value)
        self.controller.move_abs(Q_(value.value(self.axis_unit), self.axis_unit).to('µm').magnitude)

    def move_rel(self, value: DataActuator):
        value = self.check_bound(self.current_value + value) - self.current_value
        self.target_value = value + self.current_value
        value = self.set_position_relative_with_scaling(value)
        self.controller.move_rel(Q_(value.value(self.axis_unit), self.axis_unit).to('µm').magnitude)

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
            self.controller.velocity_um_s = q_from_param(param).to('µm/s').magnitude
            self._update_timeout()
        elif param.name() in self.TWINS_ATTRIBUTES:
            self._apply_twins(param.name(), param)


if __name__ == '__main__':
    main(__file__)
