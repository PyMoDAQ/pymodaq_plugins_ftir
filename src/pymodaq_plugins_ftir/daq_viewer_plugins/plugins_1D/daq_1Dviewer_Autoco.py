import numpy as np
from qtpy.QtCore import QThread, QObject, Slot
from easydict import EasyDict as edict
from pymodaq.utils.daq_utils import ThreadCommand, getLineInfo, DataFromPlugins, Axis, set_logger, get_module_name
from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.parameter.utils import iter_children
from pymodaq_plugins_daqmx.hardware.national_instruments.daqmx import DAQmx, ClockSettings, AIChannel
from pymodaq_plugins_ftir.utils.configuration import ConfigFTIR as Config
from pymodaq_plugins_ftir.daq_viewer_plugins.plugins_0D.daq_0Dviewer_Diodes import DAQ_0DViewer_Diodes, device_ai, \
    ai_monitor_plus, ai_monitor_minus, ai_diff
from pymodaq_plugins_smaract.daq_move_plugins.daq_move_SmarAct import DAQ_Move_SmarAct
logger = set_logger(get_module_name(__file__))

config = Config()


class DAQ_1DViewer_Autoco(DAQ_0DViewer_Diodes, DAQ_Move_SmarAct, QObject):
    """
    """

    hardware_averaging = False
    live_mode_available = False

    params = [

        {"title": "positions:", "name": "positions", "type": "group", "children": [
            {"title": "Start:", "name": "start", "type": "float", "value": config('delay', 'positions', 'start')},
            {"title": "Stop:", "name": "stop", "type": "float", "value": config('delay', 'positions', 'stop')},
            {"title": "Go to:", "name": "go_to", "type": "float", "value": config('delay', 'positions', 'go_to')},
            {"title": "Move to:", "name": "move_to", "type": "bool_push", "value": False},
            {"title": "Move Home:", "name": "move_home", "type": "bool_push", "value": False},
        ]}] + \
        DAQ_0DViewer_Diodes.params + DAQ_Move_SmarAct.params

    def __init__(self, parent=None, params_state=None):
        QObject.__init__(self)
        DAQ_0DViewer_Diodes.__init__(self, parent, params_state)
        DAQ_Move_SmarAct.__init__(self, parent, params_state)

        self.controller_diodes = None
        self.controller = None

    def commit_settings(self, param):
        """
        """
        if param.name() == 'move_to':
            self.move_Abs(self.settings["positions", "go_to"])
        elif param.name() == 'move_home':
            self.move_Home()
        elif param.name() in iter_children(self.settings.child('diodes'), []):
            self.update_tasks()
        else:
            DAQ_Move_SmarAct.commit_settings(self, param)

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
                    self.controller_diodes = controller
            else:
                DAQ_0DViewer_Diodes.ini_detector(self)
                DAQ_Move_SmarAct.ini_stage(self)

                self.settings.child('epsilon').setValue(config('delay', 'epsilon'))
                self.settings.child('diodes', 'frequency').setValue(config('diodes', 'frequency'))
                self.settings.child('diodes', 'Nsamples').setValue(config('diodes', 'Nsamples'))
                self.settings.child('maxfreq').setValue(config('delay', 'maxfreq'))
                self.settings.child('positions', 'start').setValue(config('delay', 'positions', 'start'))
                self.settings.child('positions', 'stop').setValue(config('delay', 'positions', 'stop'))
                self.settings.child('positions', 'go_to').setValue(config('delay', 'positions', 'go_to'))
                #####################################

            self.update_tasks()

            self.status.info = "Current measurement ready"
            self.status.initialized = True
            self.status.controller = self.controller_diodes
            return self.status

        except Exception as e:
            self.emit_status(ThreadCommand('Update_Status', [getLineInfo() + str(e), 'log']))
            self.status.info = getLineInfo() + str(e)
            self.status.initialized = False
            return self.status

    def close(self):
        """
        Terminate the communication protocol
        """
        DAQ_Move_SmarAct.close(self)
        ##

    def grab_data(self, Naverage=1, **kwargs):
        self.Naverage_asked = Naverage
        self.move_Abs(self.settings['positions', 'start'])

        while not np.abs(self.check_position() - self.settings['positions', 'start']) < self.settings['epsilon']:
            QThread.msleep(100)
        self.stage_done(self.check_position())

    @Slot(float)
    def stage_done(self, position: float):
        if np.abs(position - self.settings['positions', 'start']) < self.settings['epsilon']:
            self.move_Abs(self.settings['positions', 'stop'])
            super().grab_data(self.Naverage_asked)

    def emit_data(self, data):
        data_export = [np.array(data[ind]) for ind in range(len(self.channels_ai))]
        self.move_Abs(self.settings['positions', 'start'])
        self.send_data(data_export)

    def send_data(self, datatosend):
        channels_name = [ch.name for ch in self.channels_ai]
        if self.settings['diodes', 'acquisition'] != 'All':
            self.data_grabed_signal.emit([DataFromPlugins(
                name='Monitor Diodes',
                data=datatosend,
                dim=f'Data1D', labels=channels_name)])
        else:
            self.data_grabed_signal.emit([DataFromPlugins(
                name='Monitor Diodes',
                data=datatosend[0:2],
                dim=f'Data1D', labels=channels_name[0:2]),
                DataFromPlugins(
                    name='Amplified difference',
                    data=[datatosend[2]],
                    dim=f'Data1D', labels=[channels_name[2]])
            ])



    def stop(self):
        try:
            self.controller_diodes['ai'].task.StopTask()
            self.controller.stop_motion()
        except:
            pass
        ##############################

        return ''


if __name__ == '__main__':
    main(__file__)
