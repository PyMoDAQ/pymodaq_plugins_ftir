import numpy as np

from pymodaq_data.data import DataToExport

from pymodaq.control_modules.viewer_utility_classes import main
from pymodaq.utils.data import DataFromPlugins

from pymodaq_plugins_ftir.daq_viewer_plugins.plugins_1D.daq_1Dviewer_FTIRCardSim import (
    DAQ_1DViewer_FTIRCardSim, MONITORS)
from pymodaq_plugins_ftir.hardware.twins_simulator import CHANNEL_LABELS, AcquisitionResult


class DAQ_0DViewer_FTIRCardSim(DAQ_1DViewer_FTIRCardSim):
    """Simulated acquisition card of the TWINS spectrometer, averaged: one value (mean of Nsamples) per channel

    Same simulated card as ``DAQ_1DViewer_FTIRCardSim``, but each grab emits the mean of the samples: this is the
    detector to use for a step by step scan of the stage (move, stop, measure), for instance with the DAQ_Scan
    extension of PyMoDAQ, the stage being ``DAQ_Move_FTIRStageSim``. Use few samples (the mean of a grab acquired
    during a move blurs the fringes).

    Tested with PyMoDAQ 5.3.12, Python 3.13, Linux, against the simulator only (there is no hardware behind it).
    """
    params = DAQ_1DViewer_FTIRCardSim.params

    def ini_detector(self, controller=None):
        info, initialized = super().ini_detector(controller)
        if self.settings['n_samples'] > 1000:  # a sensible default for a step by step scan: 10 ms per point
            self.settings.child('n_samples').setValue(20)
            self._update_duration()
        return info, initialized

    def make_dte(self, result: AcquisitionResult) -> DataToExport:
        data = []
        monitors = [ch for ch in MONITORS if ch in result.data]
        if monitors:
            data.append(DataFromPlugins(name='Monitor diodes',
                                        data=[np.array([np.mean(result.data[ch])]) for ch in monitors],
                                        dim='Data0D', labels=[CHANNEL_LABELS[ch] for ch in monitors], units='V'))
        if 'diff' in result.data:
            data.append(DataFromPlugins(name='Amplified difference', data=[np.array([np.mean(result.data['diff'])])],
                                        dim='Data0D', labels=[CHANNEL_LABELS['diff']], units='V'))
        if self.settings['export_positions']:
            data.append(DataFromPlugins(name='Stage position', data=[np.array([np.mean(result.positions_um)])],
                                        dim='Data0D', labels=['Stage position (simulation)'], units='µm'))
        return DataToExport('FTIRCardSim', data=data)


if __name__ == '__main__':
    main(__file__)
