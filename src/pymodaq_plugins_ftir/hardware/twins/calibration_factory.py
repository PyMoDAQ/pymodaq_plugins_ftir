# -*- coding: utf-8 -*-
"""Factory of calibrations: how the birefringence ``delta_n(l)`` is known when converting a thickness difference of
birefringent material to a wavelength. Pure numpy (no Qt, no PyMoDAQ).

The interferogram is ``I(e) = integral S(l) cos(2 pi delta_n(l) e / l) dl`` so the analysis only needs the law
``delta_n(l)``. Same pattern as the other factories of PyMoDAQ (loss functions of the adaptive extension...): a base
class, a ``register`` decorator and a folder (``calibrations/``) holding one module per calibration, all imported
automatically (``import pymodaq_plugins_ftir.hardware.twins.calibrations``)::

    from pymodaq_plugins_ftir.hardware.twins.calibration_factory import CalibrationFactory

    @CalibrationFactory.register()
    class MyCalibration(CalibrationBase):
        usual_name = 'My calibration'
        params = [{'title': 'Value:', 'name': 'value', 'type': 'float', 'value': 0.12}]  # for a settings tree

        def __init__(self, value=0.12): ...
        def delta_n(self, wavelength_nm): ...

    CalibrationFactory.create('My calibration', value=0.11)
"""
from abc import ABCMeta, abstractmethod
from typing import Callable, List, Optional, Tuple, Type

import numpy as np

from pymodaq_utils.logger import set_logger, get_module_name

logger = set_logger(get_module_name(__file__))


class CalibrationBase(metaclass=ABCMeta):
    usual_name: str  # key used in the factory
    params: List[dict] = []  # parameters of the constructor, as a list of dict (pyqtgraph Parameter style)

    @abstractmethod
    def delta_n(self, wavelength_nm):
        """Birefringence at the given wavelength(s) (nm)"""

    def spectrum(self, thickness_nm: np.ndarray, signal: np.ndarray, wavelength_nm: Optional[np.ndarray] = None,
                 apodization: Optional[str] = 'hann') -> Tuple[np.ndarray, np.ndarray]:
        """Spectrum (modulus of the FFT) against wavelength (nm) of an interferogram sampled regularly against the
        thickness difference (nm). The FFT against ``e`` is the spectrum against ``k = delta_n(l) / l`` (cycles/nm),
        mapped to wavelength with this calibration (and the Jacobian ``dk/dl``)."""
        thickness_nm = np.asarray(thickness_nm, dtype=float)
        signal = np.asarray(signal, dtype=float) - np.mean(signal)
        if apodization == 'hann':
            signal = signal * np.hanning(signal.size)
        de = float(np.mean(np.diff(thickness_nm)))
        spec_k = np.abs(np.fft.rfft(signal))
        k = np.fft.rfftfreq(signal.size, d=abs(de))
        wl = np.linspace(250., 1600., 4000) if wavelength_nm is None else np.asarray(wavelength_nm, dtype=float)
        k_of_l = self.delta_n(wl) / wl
        jacobian = np.abs(np.gradient(k_of_l, wl))
        return wl, np.interp(k_of_l, k, spec_k, left=0., right=0.) * jacobian


class CalibrationFactory:
    _builders = {}

    @classmethod
    def register(cls) -> Callable:
        """ To be used as a decorator

        Register in the class registry a new calibration class using its ``usual_name``
        """

        def inner_wrapper(wrapped_class: Type[CalibrationBase]) -> Type[CalibrationBase]:
            key = wrapped_class.usual_name
            if key not in cls._builders:
                cls._builders[key] = wrapped_class
            else:
                logger.warning(f'The {key} calibration is already registered. Replacing it')
                cls._builders[key] = wrapped_class
            return wrapped_class

        return inner_wrapper

    @classmethod
    def keys(cls) -> List[str]:
        return list(cls._builders)

    @classmethod
    def get(cls, key: str) -> Type[CalibrationBase]:
        try:
            return cls._builders[key]
        except KeyError:
            raise ValueError(f'Unknown calibration {key!r}, choose among {cls.keys()}') from None

    @classmethod
    def create(cls, key: str, **kwargs) -> CalibrationBase:
        return cls.get(key)(**kwargs)
