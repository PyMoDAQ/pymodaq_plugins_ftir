import numpy as np
from qtpy.QtCore import QThread
from easydict import EasyDict as edict
from pymodaq.daq_utils.daq_utils import ThreadCommand, getLineInfo, DataFromPlugins, Axis, set_logger, get_module_name
from pymodaq.daq_viewer.utility_classes import DAQ_Viewer_base, comon_parameters, main

from pymodaq_plugins_daqmx.hardware.national_instruments.daqmx import DAQmx, ClockSettings, AIChannel
from pymodaq_plugins_ftir.utils.configuration import ConfigFTIR as Config

logger = set_logger(get_module_name(__file__))

config = Config()

device_ai = config('diodes', 'device_ai')
ai_monitor_plus = config('diodes', 'ai_monitor_plus')
ai_monitor_minus = config('diodes', 'ai_monitor_minus')
ai_diff = config('diodes', 'ai_diff')


class DAQ_0DViewer_Diodes(DAQ_Viewer_base):
    """
    """
    params = comon_parameters+[
        {'title': 'Display type:', 'name': 'display', 'type': 'list', 'limits': ['0D', '1D']},
        {'title': 'Frequency Acq.:', 'name': 'frequency', 'type': 'int', 'value': 1000, 'min': 1},
        {'title': 'Nsamples:', 'name': 'Nsamples', 'type': 'int', 'value': 100, 'default': 100, 'min': 1},
        {'title': 'Monitor +:', 'name': 'ai_monitor_plus', 'type': 'list',
         'limits': DAQmx.get_NIDAQ_channels(source_type='Analog_Input'), 'value': f'{device_ai}/{ai_monitor_plus}'},
        {'title': 'Monitor -:', 'name': 'ai_monitor_minus', 'type': 'list',
         'limits': DAQmx.get_NIDAQ_channels(source_type='Analog_Input'), 'value': f'{device_ai}/{ai_monitor_minus}'},
        {'title': 'Diff:', 'name': 'ai_diff', 'type': 'list',
         'limits': DAQmx.get_NIDAQ_channels(source_type='Analog_Input'), 'value': f'{device_ai}/{ai_diff}'},
        ]
    hardware_averaging = True
    live_mode_available = True

    def __init__(self, parent=None, params_state=None):
        super().__init__(parent, params_state)

        self.channels_ai = None
        self.clock_settings = None
        self.data_tot = None
        self.live = False
        self.Naverage = 1
        self.ind_average = 0
        self.clock_settings_ai = None

    def commit_settings(self, param):
        """
        """

        self.update_tasks()

    def ini_detector(self, controller=None):
        """Detector communication initialization

        Parameters
        ----------
        controller: (object) custom object of a PyMoDAQ plugin (Slave case). None if only one detector by controller (Master case)

        Returns
        -------
        self.status (edict): with initialization status: three fields:
            * info (str)
            * controller (object) initialized controller
            *initialized: (bool): False if initialization failed otherwise True
        """

        try:
            self.status.update(edict(initialized=False,info="", x_axis=None,y_axis=None,controller=None))
            if self.settings.child(('controller_status')).value() == "Slave":
                if controller is None:
                    raise Exception('no controller has been defined externally while this detector is a slave one')
                else:
                    self.controller = controller
            else:

                self.controller = dict(ai=DAQmx())
                #####################################

            self.update_tasks()


            self.status.info = "Current measurement ready"
            self.status.initialized = True
            self.status.controller = self.controller
            return self.status

        except Exception as e:
            self.emit_status(ThreadCommand('Update_Status', [getLineInfo() + str(e), 'log']))
            self.status.info = getLineInfo() + str(e)
            self.status.initialized = False
            return self.status

    def update_tasks(self):

        self.channels_ai = [AIChannel(name=self.settings.child('ai_monitor_plus').value(),
                                      source='Analog_Input', analog_type='Voltage',
                                      value_min=-10., value_max=10., termination='Diff', ),
                            AIChannel(name=self.settings.child('ai_monitor_minus').value(),
                                      source='Analog_Input', analog_type='Voltage',
                                      value_min=-10., value_max=10., termination='Diff', ),
                            AIChannel(name=self.settings.child('ai_diff').value(),
                                      source='Analog_Input', analog_type='Voltage',
                                      value_min=-10., value_max=10., termination='Diff', ),
                            ]

        self.clock_settings_ai = ClockSettings(frequency=self.settings.child('frequency').value(),
                                               Nsamples=self.settings.child('Nsamples').value(), repetition=self.live)

        self.controller['ai'].update_task(self.channels_ai, self.clock_settings_ai)



    def close(self):
        """
        Terminate the communication protocol
        """
        pass
        ##

    def grab_data(self, Naverage=1, **kwargs):
        """

        Parameters
        ----------
        Naverage: (int) Number of hardware averaging
        kwargs: (dict) of others optionals arguments
        """
        

        update = False

        if 'live' in kwargs:
            if kwargs['live'] != self.live:
                update = True
            self.live = kwargs['live']

        if Naverage != self.Naverage:
            self.Naverage = Naverage
            update = True

        if update:
            self.update_tasks()

        self.ind_average = 0
        self.data_tot = np.zeros((len(self.channels_ai), self.clock_settings_ai.Nsamples))

        while not self.controller['ai'].isTaskDone():
            self.stop()
        if self.controller['ai'].c_callback is None:
            self.controller['ai'].register_callback(self.read_data, 'Nsamples', self.clock_settings_ai.Nsamples)
        self.controller['ai'].task.StartTask()
        #QThread.msleep(500)
        #self.read_data(None, 0)

    def read_data(self, taskhandle, status, samples=0, callbackdata=None):
        #print(f'going to read {self.clock_settings_ai.Nsamples} samples, callbakc {samples}')
        data = self.controller['ai'].readAnalog(len(self.channels_ai), self.clock_settings_ai)
        if not self.live:
            self.stop()
        self.ind_average += 1

        self.data_tot += 1 / self.Naverage * data.reshape(len(self.channels_ai), self.clock_settings_ai.Nsamples)

        if self.ind_average == self.Naverage:
            self.emit_data(self.data_tot)
            self.ind_average = 0
            self.data_tot = np.zeros((len(self.channels_ai), self.clock_settings_ai.Nsamples))

        return 0  #mandatory for the PyDAQmx callback

    def emit_data(self, data):
        channels_name = [ch.name for ch in self.channels_ai]

        if self.settings.child('display').value() == '0D':
            data = np.mean(data, 1)

        #data = np.squeeze(data)
        # print(f'shape is {data.shape}')
        # print(data)
        if len(self.channels_ai) == 1 and data.size == 1:
            data_export = [np.array([data[0]])]
        else:
            data_export = [np.squeeze(data[ind]) for ind in range(len(self.channels_ai))]

        if self.settings.child('display').value() == '0D':
            datatosend1 = [np.array([data_export[ind]]) for ind in range(len(self.channels_ai)-1)]
            datatosend2 = [np.array([data_export[2]])]
        else:
            datatosend1 = [d for d in data_export[0:2]]
            datatosend2 = [data_export[2]]

        # print(f'data len is {len(data_export)} and shape is {data_export[0].shape}')
        self.data_grabed_signal.emit([DataFromPlugins(
            name='Monitor Diodes',
            data=datatosend1,
            dim=f'Data{self.settings.child("display").value()}', labels=channels_name[0:2]),
            DataFromPlugins(
                name='Diff Diodes',
                data=datatosend2,
                dim=f'Data{self.settings.child("display").value()}', labels=channels_name[2])]
        )

    def stop(self):
        try:
            self.controller['ai'].task.StopTask()
        except:
            pass
        ##############################

        return ''


if __name__ == '__main__':
    main(__file__)
