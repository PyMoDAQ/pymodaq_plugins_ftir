from pymodaq.daq_move.utility_classes import DAQ_Move_base  # base class
from pymodaq.daq_move.utility_classes import comon_parameters  # common set of parameters for all actuators
from pymodaq.daq_utils.daq_utils import ThreadCommand, getLineInfo  # object used to send info back to the main thread
from easydict import EasyDict as edict  # type of dict
import numpy as np
from pymodaq_plugins_daqmx.hardware.national_instruments.daqmx import DAQmx, DAQ_analog_types, DAQ_thermocouples,\
    DAQ_termination, Edge, DAQ_NIDAQ_source, \
    ClockSettings, ChangeDetectionSettings,AIChannel, Counter, AIThermoChannel, AOChannel, TriggerSettings, DOChannel, DIChannel
from pymodaq.daq_utils import gui_utils as gutils
from pymodaq.daq_utils.parameter import utils as putils
from pymodaq.daq_utils.parameter import parameterTypes as ptypes
from pymodaq.daq_utils import config as config_mod


from pymodaq_plugins_ftir.utils.configuration import ConfigMoKe

config = ConfigMoKe()
device_ao = config('micro', 'current', 'device_ao')
channel_ao = config('micro', 'current', 'channel_ao')
device_ai = config('micro', 'current', 'device_ai')
channel_ai = config('micro', 'current', 'channel_ai')
resistor = config('micro', 'current', 'resistor')


class DAQ_Move_Current(DAQ_Move_base):
    """
        Wrapper object to access the Mock fonctionnalities, similar wrapper for all controllers.

        =============== ==============
        **Attributes**    **Type**
        *params*          dictionnary
        =============== ==============
    """
    _controller_units = 'Volts'
    ao_limits = [-1, 1]
    _epsilon = 0.005

    is_multiaxes = False  # set to True if this plugin is controlled for a multiaxis controller (with a unique communication link)
    stage_names = []
    params = [ {'title': 'Device:', 'name': 'device', 'type': 'list',
                      'values': DAQmx.get_NIDAQ_devices(), 'value': device_ao},
                 {'title': 'AO Voltage:', 'name': 'ao', 'type': 'group', 'children': [
                     {'title': 'Name:', 'name': 'ao_channel', 'type': 'list',
                      'values': DAQmx.get_NIDAQ_channels(devices=[device_ao], source_type='Analog_Output'),
                      'value': f'{device_ao}/{channel_ao}'},
                     {'title': 'Min:', 'name': 'ao_min', 'type': 'list',
                      'values': [r[0] for r in DAQmx.getAOVoltageRange(device_ao)]},
                     {'title': 'Max:', 'name': 'ao_max', 'type': 'list',
                      'values': [r[1] for r in DAQmx.getAOVoltageRange(device_ao)]},
                     {'title': 'Scaling:', 'name': 'controller_scaling', 'type': 'float', 'value': 0.402}
                 ]},
               {'title': 'AI Voltage:', 'name': 'ai', 'type': 'group', 'children': [
                   {'title': 'Name:', 'name': 'ai_channel', 'type': 'list',
                    'values': DAQmx.get_NIDAQ_channels(devices=[device_ai], source_type='Analog_Input'),
                    'value': f'{device_ai}/{channel_ai}'},
                   {'title': 'Min:', 'name': 'ai_min', 'type': 'list',
                    'values': [r[0] for r in DAQmx.getAIVoltageRange(device_ai)]},
                   {'title': 'Max:', 'name': 'ai_max', 'type': 'list',
                    'values': [r[1] for r in DAQmx.getAIVoltageRange(device_ai)]},
                   {'title': 'Resistor (Ohm):', 'name': 'resistor', 'type': 'float',
                    'value': resistor},
                   {'title': 'Use it?', 'name': 'use_R', 'type': 'bool', 'value': True},
               ]},
               
                 {'title': 'MultiAxes:', 'name': 'multiaxes', 'type': 'group', 'visible': is_multiaxes, 'children': [
                     {'title': 'is Multiaxes:', 'name': 'ismultiaxes', 'type': 'bool', 'value': is_multiaxes,
                      'default': False},
                     {'title': 'Status:', 'name': 'multi_status', 'type': 'list', 'value': 'Master',
                      'values': ['Master', 'Slave']},
                     {'title': 'Axis:', 'name': 'axis', 'type': 'list', 'values': stage_names}, ]}] \
             + comon_parameters

    def __init__(self, parent=None, params_state=None):
        """
            Initialize the the class

            ============== ================================================ ==========================================================================================
            **Parameters**  **Type**                                         **Description**

            *parent*        Caller object of this plugin                    see DAQ_Move_main.DAQ_Move_stage
            *params_state*  list of dicts                                   saved state of the plugins parameters list
            ============== ================================================ ==========================================================================================

        """

        super().__init__(parent, params_state)

    def check_position(self):
        """Get the current position from the hardware with scaling conversion.

        Returns
        -------
        float: The position obtained after scaling conversion.
        """
        #pos = self.target_position

        while not self.controller['ai'].isTaskDone():
            self.controller['ai'].task.StopTask()

        data = self.controller['ai'].readAnalog(len(self.channels_ai), self.clock_settings_ai)
        pos = np.mean(data) / self.settings.child('ai', 'resistor').value()
        pos = self.get_position_with_scaling(pos)

        self.emit_status(ThreadCommand('check_position', [pos]))
        return pos


    def close(self):
        """
        Terminate the communication protocol
        """
        pass
        ##

    def commit_settings(self, param):
        """
            | Activate any parameter changes on the PI_GCS2 hardware.
            |
            | Called after a param_tree_changed signal from DAQ_Move_main.

        """
        if param.name() == 'device':
            channels = DAQmx.get_NIDAQ_channels(devices=[param.value()], source_type='Analog_Output')
            self.settings.child('ao', 'ao_channel').setOpts(limits=channels)

        if param.name() == 'ao_channel':
            self.get_dynamics()

        self.update_tasks()

    def get_dynamics(self):
        device = self.settings.child('device').value()
        ranges = self.controller['ao'].getAIVoltageRange(device)

        self.settings.child('ao', 'ao_min').setOpts(limits=[r[0] for r in ranges])
        self.settings.child('ao', 'ao_max').setOpts(limits=[r[1] for r in ranges])

    def ini_stage(self, controller=None):
        """Actuator communication initialization

        Parameters
        ----------
        controller: (object) custom object of a PyMoDAQ plugin (Slave case). None if only one actuator by controller (Master case)

        Returns
        -------
        self.status (edict): with initialization status: three fields:
            * info (str)
            * controller (object) initialized controller
            *initialized: (bool): False if initialization failed otherwise True
        """


        try:
            # initialize the stage and its controller status
            # controller is an object that may be passed to other instances of DAQ_Move_Mock in case
            # of one controller controlling multiactuators (or detector)

            self.status.update(edict(info="", controller=None, initialized=False))

            # check whether this stage is controlled by a multiaxe controller (to be defined for each plugin)
            # if multiaxes then init the controller here if Master state otherwise use external controller
            if self.settings.child('multiaxes', 'ismultiaxes').value() and self.settings.child('multiaxes',
                                   'multi_status').value() == "Slave":
                if controller is None:
                    raise Exception('no controller has been defined externally while this axe is a slave one')
                else:
                    self.controller = controller
            else:  # Master stage

                self.controller = dict(ao=DAQmx(), ai=DAQmx())

            self.update_tasks()

            self.status.info = "Controller to get/set the current in coil"
            self.status.controller = self.controller
            self.status.initialized = True
            return self.status

        except Exception as e:
            self.emit_status(ThreadCommand('Update_Status', [getLineInfo() + str(e), 'log']))
            self.status.info = getLineInfo() + str(e)
            self.status.initialized = False
            return self.status

    def update_tasks(self):

        self.channels_ao = [AOChannel(name=self.settings.child('ao', 'ao_channel').value(),
                                   source='Analog_Output', analog_type='Voltage',
                                   value_min=self.settings.child('ao', 'ao_min').value(),
                                   value_max=self.settings.child('ao', 'ao_max').value())]

        self.channels_ai = [AIChannel(name=self.settings.child('ai', 'ai_channel').value(),
                                   source='Analog_Input', analog_type='Voltage',
                                   value_min=self.settings.child('ai', 'ai_min').value(),
                                   value_max=self.settings.child('ai', 'ai_max').value())]

        self.stop_task_and_zero()

        clock_settings = ClockSettings(frequency=1000, Nsamples=1)
        self.controller['ao'].update_task(self.channels_ao, clock_settings)

        self.clock_settings_ai = ClockSettings(frequency=1000, Nsamples=10)
        self.controller['ai'].update_task(self.channels_ai, self.clock_settings_ai)


    def stop_task_and_zero(self, zero=0.):

        if self.controller['ao'].task is not None:
            if not self.controller['ao'].isTaskDone():
                self.controller['ao'].stop()

        clock_settings = ClockSettings(frequency=1000, Nsamples=1)
        self.controller['ao'].update_task(self.channels_ao, clock_settings)
        self.write_ao(0.)
        self.controller['ao'].stop()

    def move_Abs(self, position):
        """ Move the actuator to the absolute target defined by position

        Parameters
        ----------
        position: (flaot) value of the absolute target positioning
        """

        position = self.check_bound(position)  #if user checked bounds, the defined bounds are applied here
        self.target_position = position
        position = self.set_position_with_scaling(position)  # apply scaling if the user specified one
        self.write_ao(position / self.settings.child('ao', 'controller_scaling').value())

    def move_Rel(self, position):
        """ Move the actuator to the relative target actuator value defined by position

        Parameters
        ----------
        position: (flaot) value of the relative target positioning
        """
        position = self.check_bound(self.current_position + position) - self.current_position
        self.target_position = position + self.current_position
        position = self.set_position_relative_with_scaling(position)
        self.write_ao(self.target_position / self.settings.child('ao', 'controller_scaling').value())

    def write_ao(self, voltage):
        self.controller['ao'].writeAnalog(1, len(self.channels_ao),
                                          np.array([voltage for ind in range(len(self.channels_ao))],
                                                   dtype=np.float),
                                          autostart=True)
    def move_Home(self):
        """
          Send the update status thread command.
            See Also
            --------
            daq_utils.ThreadCommand
        """

        self.stop_task_and_zero()
        ##############################


    def stop_motion(self):
      """
        Call the specific move_done function (depending on the hardware).

        See Also
        --------
        move_done
      """

      self.move_done() #to let the interface know the actuator stopped
      ##############################


def main():
    import sys
    from PyQt5 import QtWidgets
    from pymodaq.daq_move.daq_move_main import DAQ_Move
    from pathlib import Path
    app = QtWidgets.QApplication(sys.argv)
    Form = QtWidgets.QWidget()
    prog = DAQ_Move(Form, title="test",)
    Form.show()
    prog.actuator = Path(__file__).stem[9:]
    prog.init()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
