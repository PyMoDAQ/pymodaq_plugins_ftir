from pymodaq.daq_move.utility_classes import DAQ_Move_base  # base class
from pymodaq.daq_move.utility_classes import comon_parameters  # common set of parameters for all actuators
from pymodaq.daq_utils.daq_utils import ThreadCommand, getLineInfo  # object used to send info back to the main thread
from easydict import EasyDict as edict  # type of dict
import numpy as np
from pymodaq_plugins_daqmx.hardware.national_instruments.daqmx import DAQmx, DAQ_analog_types, DAQ_thermocouples,\
    DAQ_termination, Edge, DAQ_NIDAQ_source, \
    ClockSettings, ChangeDetectionSettings, AIChannel, Counter, AIThermoChannel, AOChannel,\
    TriggerSettings, DOChannel, DIChannel
from pymodaq.daq_utils import gui_utils as gutils
from pymodaq.daq_utils.parameter import utils as putils
from pymodaq.daq_utils.parameter import parameterTypes as ptypes


from pymodaq_plugins_ftir.utils.configuration import ConfigMoKe

config = ConfigMoKe()
device = config('micro', 'led', 'device_ao')
ao_channels = config('micro', 'led', 'channels_ao')
di_name = f"{config('micro', 'led', 'device_di')}/" \
          f"{config('micro', 'led', 'port_di')}/" \
          f"{config('micro', 'led', 'line_di')}"

channels = ['top', 'left', 'right', 'bottom']
led_limit = 3.5

class DAQ_Move_LedDC4104(DAQ_Move_base):
    """
        Wrapper object to access the Mock fonctionnalities, similar wrapper for all controllers.

        =============== ==============
        **Attributes**    **Type**
        *params*          dictionnary
        =============== ==============
    """
    _controller_units = 'Volts'

    is_multiaxes = True  # set to True if this plugin is controlled for a multiaxis controller (with a unique communication link)
    stage_names = ['offset', 'top', 'left', 'right', 'bottom']  # "list of strings of the multiaxes

    params = [{'title': f'{channels[ind]} LED:', 'name': channels[ind], 'type': 'group', 'children': [
                     {'title': 'Name:', 'name': f'{channels[ind]}_ao', 'type': 'list',
                      'limits': DAQmx.get_NIDAQ_channels(source_type='Analog_Output'),
                      'value': f'{device}/{ao_channels[ind]}'},
                     {'title': 'Value:', 'name': f'{channels[ind]}_val', 'type': 'float', 'value': 0, 'min': 0,
                      'max': led_limit},
                     {'title': 'Activated?:', 'name': f'{channels[ind]}_act', 'type': 'led_push', 'value': False}
                 ]} for ind in range(len(ao_channels))] + \
             [{'title': 'Offset:', 'name': 'offset', 'type': 'slide', 'subtype': 'lin', 'value': 0.0,
               'limits': [0, led_limit]},
              {'title': 'Activate All:', 'name': 'activate_all', 'type': 'led_push', 'value': False},
              {'title': 'Digital Triggering:', 'name': 'digital', 'type': 'group', 'children': [
                  {'title': 'Change on:', 'name': 'digital_di', 'type': 'list',
                   'limits': DAQmx.get_NIDAQ_channels(source_type='Digital_Input'),
                   'value': di_name},
                  {'title': 'Clock on:', 'name': 'digital_clock', 'type': 'list',
                   'limits': DAQmx.get_NIDAQ_channels(source_type='Terminals'),
                   'value': f"/{config('micro', 'led', 'changedetectionevent_device')}/ChangeDetectionEvent"},
                  {'title': 'Activated?:', 'name': 'digital_act', 'type': 'led_push', 'value': False},
              ]}] + \
             [{'title': 'MultiAxes:', 'name': 'multiaxes', 'type': 'group', 'visible': is_multiaxes, 'children': [
                 {'title': 'is Multiaxes:', 'name': 'ismultiaxes', 'type': 'bool', 'value': is_multiaxes,
                  'default': False},
                 {'title': 'Status:', 'name': 'multi_status', 'type': 'list', 'value': 'Master',
                  'limits': ['Master', 'Slave']},
                 {'title': 'Axis:', 'name': 'axis', 'type': 'list',  'limits': stage_names}]}] + \
             comon_parameters

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
        self.led_values = dict(zip(channels, [{f'{chan}_act': False,
                                                    f'{chan}_val': 0.} for chan in channels]))
        self.led_type = 'manual'

        self.sequence_list = [dict(top=True, bottom=False, left=False, right=False),
                              dict(top=False, bottom=True, left=False, right=False),]

    def check_position(self):
        """Get the current position from the hardware with scaling conversion.

        Returns
        -------
        float: The position obtained after scaling conversion.
        """

        pos = self.target_position
        ##

        pos = self.get_position_with_scaling(pos)
        self.emit_status(ThreadCommand('check_position',[pos]))
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

        if param.name() == "activate_all":
            for channel in channels:
                self.settings.child(channel, f'{channel}_act').setValue(param.value())

        flag = '_act' in param.name() or '_val' in param.name() or 'offset' in param.name() or \
               'activate_all' in param.name()
        if flag and 'digital_act' != param.name() and not self.settings.child('digital', 'digital_act').value():
            """
            If only activated state or value of the led is changed, just update the "manual" value, else update the task
            """
            self.check_led_and_update()
        else:
            self.update_tasks()

    def set_leds_external(self, led_values):
        for led in led_values:
            self.settings.child(led, f'{led}_act').setValue(led_values[led][f'{led}_act'])
            self.settings.child(led, f'{led}_val').setValue(led_values[led][f'{led}_val'])
        self.check_led_and_update()

    def set_led_type(self, led_type_dict):
        """
        Set the type of control for the LEDs. If set to sequence, the daqmx task is clocked on the changed state of a
        digital channel receiving a high TTL state when the Camera is acquirring
        Parameters
        ----------
        led_type_dict: (dict) with  a key either 'manual' or 'sequence'
            In the case of sequence, the associated value is a list of dict containing the status of the LEDs

        Returns
        -------

        """

        is_sequence = 'sequence' in led_type_dict
        if is_sequence:
            self.sequence_list = led_type_dict['sequence']

        if is_sequence != self.settings.child('digital', 'digital_act').value():
            self.settings.child('digital', 'digital_act').setValue(is_sequence)
        self.update_tasks()

    def check_led_and_update(self, force_update=False):
        led_values = self.get_led_values()
        if not force_update:
            for led in led_values:
                for key in led_values[led]:
                    if led_values[led][key] != self.led_values[led][key]:
                        self.led_values = led_values
                        self.update_leds(led_values)
                        break
        else:
            self.update_leds(led_values)

    def update_leds(self, led_values):
        if self.settings.child('digital', 'digital_act').value():
            data = []
            for dic in self.sequence_list:
                data.append([led_values[channel][f'{channel}_val']
                             if dic[f'{channel}']
                             else 0. for channel in channels])
                data.append([0. for channel in led_values])
            data = np.array(list(map(list, zip(*data))),
                            dtype=np.float)  # somehow on the transpose of what you would expect
            # but cannot just use the transpose function for numpy as data are no more contiguous...

            self.controller['ao'].writeAnalog(2 * len(self.sequence_list), len(self.channels_led), data,
                                              autostart=False)

        else:
            self.controller['ao'].writeAnalog(1, 4,
                                              np.array([led_values[channel][f'{channel}_val']
                                                        if led_values[channel][f'{channel}_act']
                                                        else 0. for channel in led_values],
                                                       dtype=np.float), autostart=True)

    def limit_led_values(self, led_values):
        for channel in channels:
            led_values[channel][f'{channel}_val'] = min([led_limit, led_values[channel][f'{channel}_val']])

    def get_led_values(self):
        offset = self.settings.child('offset').value()
        led_values = dict([])
        for channel in channels:
            val = self.settings.child(channel, f'{channel}_val').value()
            activated = self.settings.child(channel, f'{channel}_act').value()
            led_values[channel] = {f'{channel}_val': val + offset,
                                   f'{channel}_act': activated}
        self.limit_led_values(led_values)
        return led_values

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

                self.controller = dict(ao=DAQmx(), di=DAQmx())

            self.update_tasks()

            self.emit_status(ThreadCommand('set_allowed_values', dict(decimals=0, minimum=0, maximum=3.5, step=0.1)))

            self.status.info = "Whatever info you want to log"
            self.status.controller = self.controller
            self.status.initialized = True
            return self.status

        except Exception as e:
            self.emit_status(ThreadCommand('Update_Status', [getLineInfo() + str(e), 'log']))
            self.status.info = getLineInfo() + str(e)
            self.status.initialized = False
            return self.status

    def update_tasks(self):

        self.channels_led = [AOChannel(name=self.settings.child(channel, f'{channel}_ao').value(),
                                       source='Analog_Output', analog_type='Voltage',
                                       value_min=-10., value_max=10.,)
                             for channel in channels]

        self.channel_clock = [DIChannel(name=self.settings.child('digital', 'digital_di').value(),
                                         source='Digital_Input')]

        self.stop_task_and_zero()

        if self.settings.child('digital', 'digital_act').value():
            clock_settings = ClockSettings(source=self.settings.child('digital', 'digital_clock').value(),
                                           frequency=1000,
                                           Nsamples=1000,
                                           repetition=True)
            digital_clock = ChangeDetectionSettings(rising_channel=self.settings.child('digital', 'digital_di').value(),
                                                    falling_channel=self.settings.child('digital', 'digital_di').value(),
                                                    repetition=True)

            self.controller['di'].update_task(self.channel_clock, digital_clock)
            self.controller['ao'].update_task(self.channels_led, clock_settings)
            self.check_led_and_update(force_update=True)

            self.controller['ao'].start()
            self.controller['di'].start()

        else:
            clock_settings = ClockSettings(frequency=1000, Nsamples=1)
            self.controller['ao'].update_task(self.channels_led, clock_settings)
            self.check_led_and_update(force_update=True)

    def stop_task_and_zero(self):
        if self.controller['ao'].task is not None:
            if not self.controller['ao'].isTaskDone():
                self.controller['ao'].stop()
        if self.controller['di'].task is not None:
            if not self.controller['di'].isTaskDone():
                self.controller['di'].stop()
        clock_settings = ClockSettings(frequency=1000, Nsamples=1)
        self.controller['ao'].update_task(self.channels_led, clock_settings)

        self.controller['ao'].writeAnalog(1, 4, np.array([0., 0., 0., 0.], dtype=np.float), autostart=True)
        self.controller['ao'].stop()

    def move_Abs(self, position):
        """ Move the actuator to the absolute target defined by position

        Parameters
        ----------
        position: (flaot) value of the absolute target positioning
        """

        position = self.check_bound(position)  #if user checked bounds, the defined bounds are applied here
        position = self.set_position_with_scaling(position)  # apply scaling if the user specified one

        axis = self.settings.child('multiaxes', 'axis').value()
        if axis != 'offset':
            self.settings.child(axis, f'{axis}_val').setValue(position)
        else:
            self.settings.child(axis).setValue(position)
        self.check_led_and_update()
        self.target_position = position

    def move_Rel(self, position):
        """ Move the actuator to the relative target actuator value defined by position

        Parameters
        ----------
        position: (flaot) value of the relative target positioning
        """
        position = self.check_bound(self.current_position+position)-self.current_position
        self.target_position = position + self.current_position

        axis = self.settings.child('multiaxes', 'axis').value()
        if axis != 'offset':
            self.settings.child(axis, f'{axis}_val').setValue(position)
        else:
            self.settings.child(axis).setValue(position)
        self.check_led_and_update()
        self.emit_status(ThreadCommand('Update_Status',['Some info you want to log']))

    def move_Home(self):
        """
          Send the update status thread command.
            See Also
            --------
            daq_utils.ThreadCommand
        """

        pass
        self.emit_status(ThreadCommand('Update_Status', ['No possible Homing']))

    def stop_motion(self):
      """
        Call the specific move_done function (depending on the hardware).

        See Also
        --------
        move_done
      """

      self.move_done() #to let the interface know the actuator stopped


def main():
    import sys
    from qtpy import QtWidgets
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
