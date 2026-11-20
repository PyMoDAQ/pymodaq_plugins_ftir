import threading
from typing import List, Optional

import numpy as np

from pymodaq_utils.utils import ThreadCommand
from pymodaq_data.data import DataToExport, Axis
from pymodaq_gui.parameter import Parameter

from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.data import DataFromPlugins

from pymodaq_plugins_ftir.utils import get_config
from pymodaq_plugins_ftir.hardware.twins_simulator import (CHANNELS, CHANNEL_LABELS, AcquisitionResult,
                                                           SimulatedAcquisitionCard, TwinsFTIRBench, get_bench,
                                                           source_presets)

MONITORS = ('monitor_plus', 'monitor_minus')


class DAQ_1DViewer_FTIRCardSim(DAQ_Viewer_base):
    """Simulated acquisition card of the TWINS Fourier transform spectrometer (MCC 128 like, 16 bits)

    No hardware: the card samples the voltages of the simulated bench of ``hardware/twins_simulator.py``, at the
    positions taken by the simulated stage (``DAQ_Move_FTIRStageSim``) during the acquisition. Three channels are
    available, as on the setup: the two monitor photodiodes (``Monitor +`` and ``Monitor -``, complementary
    interferograms) and their amplified difference (balanced detection).

    A grab acquires ``Nsamples`` samples at ``Sampling rate`` and lasts ``Nsamples / rate`` seconds in real time: start
    a move of the stage and grab to record an interferogram during a continuous scan. The data are emitted against
    time (s), the real card cannot know the stage positions; for the development of the analysis, the true positions
    can be exported too (``Export stage positions``, simulation only).

    The ``Simulation`` group changes the light source and the noise of the bench, for all the plugins sharing it.

    Tested with PyMoDAQ 5.3.12, Python 3.13, Linux, against the simulator only (there is no hardware behind it).
    """
    params = comon_parameters + [
        {'title': 'Sampling rate:', 'name': 'rate', 'type': 'float', 'suffix': 'Hz',
         'value': get_config('simulation', 'card', 'rate_hz', default=2000.), 'min': 1.,
         'max': SimulatedAcquisitionCard.max_rate_hz},
        {'title': 'Nsamples:', 'name': 'n_samples', 'type': 'int',
         'value': get_config('simulation', 'card', 'n_samples', default=2000), 'min': 1, 'max': 10_000_000},
        {'title': 'Duration:', 'name': 'duration', 'type': 'float', 'suffix': 's', 'value': 1., 'readonly': True},
        {'title': 'Input range (±V):', 'name': 'input_range', 'type': 'list',
         'limits': list(SimulatedAcquisitionCard.ranges_v),
         'value': get_config('simulation', 'card', 'input_range_v', default=10.)},
        {'title': 'Channels:', 'name': 'channels', 'type': 'group', 'children': [
            {'title': f'{CHANNEL_LABELS[ch]}:', 'name': ch, 'type': 'bool', 'value': True} for ch in CHANNELS]},
        {'title': 'Export stage positions:', 'name': 'export_positions', 'type': 'bool', 'value': False,
         'tip': 'Also emit the true stage position at each sample (simulation only, the real card cannot)'},
        {'title': 'Simulation:', 'name': 'simulation', 'type': 'group', 'children': [
            {'title': 'Light source:', 'name': 'source', 'type': 'list', 'limits': list(source_presets()),
             'value': get_config('simulation', 'source', 'preset', default='HeNe laser (632.8 nm)')},
            {'title': 'Source power:', 'name': 'power', 'type': 'float',
             'value': get_config('simulation', 'source', 'power', default=1.), 'min': 0.},
            {'title': 'Fringe visibility:', 'name': 'visibility', 'type': 'float',
             'value': get_config('simulation', 'detection', 'visibility', default=0.9), 'min': 0., 'max': 1.},
            {'title': 'Electronic noise (rms):', 'name': 'electronic_noise_v', 'type': 'float', 'suffix': 'V',
             'value': get_config('simulation', 'detection', 'electronic_noise_v', default=0.002), 'min': 0.},
            {'title': 'Intensity noise (rel. rms):', 'name': 'intensity_noise', 'type': 'float',
             'value': get_config('simulation', 'detection', 'intensity_noise', default=0.01), 'min': 0.},
            {'title': 'Intensity drift (rel.):', 'name': 'intensity_drift', 'type': 'float',
             'value': get_config('simulation', 'detection', 'intensity_drift', default=0.05), 'min': 0.},
        ]},
    ]
    hardware_averaging = False
    live_mode_available = False

    def ini_attributes(self):
        self.controller: SimulatedAcquisitionCard = None
        self.bench: TwinsFTIRBench = None
        self._thread: Optional[threading.Thread] = None

    def ini_detector(self, controller=None):
        if self.is_master:
            self.bench = get_bench(lambda *keys: get_config(*keys))
            self.controller = self.bench.card
        else:
            self.controller = controller
            self.bench = get_bench()
        for name in ('input_range', 'source', 'power', 'visibility', 'electronic_noise_v', 'intensity_noise',
                     'intensity_drift'):
            self._apply(name, self.settings.child(*self._path(name)).value())
        self._update_duration()
        return 'Simulated acquisition card ready', True

    @staticmethod
    def _path(name: str):
        return (name,) if name == 'input_range' else ('simulation', name)

    def _apply(self, name: str, value):
        if name == 'input_range':
            self.controller.input_range_v = float(value)
        elif name == 'source':
            self.bench.set_source(value)
        elif name == 'power':
            self.bench.optics.source.power = value
        else:
            setattr(self.bench.optics.detection, name, value)

    def _update_duration(self):
        self.settings.child('duration').setValue(self.settings['n_samples'] / self.settings['rate'])

    def selected_channels(self) -> List[str]:
        return [ch for ch in CHANNELS if self.settings['channels', ch]]

    def commit_settings(self, param: Parameter):
        if param.name() in ('rate', 'n_samples'):
            self._update_duration()
        elif param.name() in ('input_range', 'source', 'power', 'visibility', 'electronic_noise_v',
                              'intensity_noise', 'intensity_drift'):
            self._apply(param.name(), param.value())

    def close(self):
        if self.controller is not None:
            self.controller.abort()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def grab_data(self, Naverage=1, **kwargs):
        """Start an acquisition in a thread (as the callback of a real card), the data are emitted at its end"""
        channels = self.selected_channels()
        if not channels:
            self.emit_status(ThreadCommand('Update_Status', ['Select at least one channel']))
            return
        if self._thread is not None and self._thread.is_alive():
            self.controller.abort()
            self._thread.join()
        n_samples, rate = self.settings['n_samples'], self.settings['rate']
        self._thread = threading.Thread(target=self._acquire, args=(n_samples, rate, channels), daemon=True)
        self._thread.start()

    def _acquire(self, n_samples: int, rate: float, channels: List[str]):
        try:
            result = self.controller.acquire(n_samples, rate, channels)
        except Exception as e:  # this thread is not the plugin one: report instead of raising
            self.emit_status(ThreadCommand('Update_Status', [f'Acquisition failed: {e}', 'log']))
            return
        self.dte_signal.emit(self.make_dte(result))

    def make_dte(self, result: AcquisitionResult) -> DataToExport:
        axis = Axis('Time', units='s', data=result.times_s, index=0)
        data = []
        monitors = [ch for ch in MONITORS if ch in result.data]
        if monitors:
            data.append(DataFromPlugins(name='Monitor diodes', data=[result.data[ch] for ch in monitors],
                                        dim='Data1D', labels=[CHANNEL_LABELS[ch] for ch in monitors],
                                        units='V', axes=[axis]))
        if 'diff' in result.data:
            data.append(DataFromPlugins(name='Amplified difference', data=[result.data['diff']], dim='Data1D',
                                        labels=[CHANNEL_LABELS['diff']], units='V', axes=[axis.copy()]))
        if self.settings['export_positions']:
            data.append(DataFromPlugins(name='Stage position', data=[np.asarray(result.positions_um)],
                                        dim='Data1D', labels=['Stage position (simulation)'], units='µm',
                                        axes=[axis.copy()]))
        return DataToExport('FTIRCardSim', data=data)

    def stop(self):
        if self.controller is not None:
            self.controller.abort()
        return ''


if __name__ == '__main__':
    main(__file__)
