"""Calibrations of the TWINS: how the birefringence ``delta_n(l)`` is known when converting a thickness difference to a
wavelength. Pure numpy (no Qt, no PyMoDAQ).

The interferogram is ``I(e) = integral S(l) cos(2 pi delta_n(l) e / l) dl`` so the analysis only needs the law
``delta_n(l)``. Three ways to know it, chosen with :func:`make_calibration` (factory)::

    make_calibration('single point', wavelength_nm=632.8, delta_n=0.1212)  # one laser line, dispersion ignored
    make_calibration('sellmeier', material=ALPHA_BBO)                      # trust the Sellmeier equations
    make_calibration('polynomial', coefficients=[0.1212, -0.02], reference_nm=632.8)  # fitted on known lines

New kinds are added with :func:`register_calibration`.
"""
from abc import ABC, abstractmethod
from typing import Callable, Dict, Optional, Sequence, Tuple, Type, Union

import numpy as np

from pymodaq_plugins_ftir.hardware.twins_simulator import ALPHA_BBO, MATERIALS, SellmeierBirefringent


class Calibration(ABC):
    """Law of the birefringence against wavelength"""

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


class SinglePointCalibration(Calibration):
    """One calibration point (a laser line): ``delta_n`` known at ``wavelength_nm``, constant elsewhere"""

    def __init__(self, wavelength_nm: float = 632.8, delta_n: Optional[float] = None,
                 material: SellmeierBirefringent = ALPHA_BBO):
        self.wavelength_nm = float(wavelength_nm)
        self.value = float(material.delta_n(wavelength_nm) if delta_n is None else delta_n)

    def delta_n(self, wavelength_nm):
        return np.full(np.shape(wavelength_nm), self.value)


class SellmeierCalibration(Calibration):
    """Trust the Sellmeier equations of the material"""

    def __init__(self, material: Union[str, SellmeierBirefringent] = ALPHA_BBO):
        self.material = MATERIALS[material] if isinstance(material, str) else material

    def delta_n(self, wavelength_nm):
        return self.material.delta_n(wavelength_nm)


class PolynomialCalibration(Calibration):
    """Custom polynomial ``delta_n = sum c_i x^i`` with ``x = (l - reference_nm) / 1000`` (µm), lowest order first.
    Coefficients can be fitted on known lines with :meth:`fit`."""

    def __init__(self, coefficients: Sequence[float], reference_nm: float = 632.8):
        self.coefficients = np.asarray(coefficients, dtype=float)
        self.reference_nm = float(reference_nm)

    def delta_n(self, wavelength_nm):
        x = (np.asarray(wavelength_nm, dtype=float) - self.reference_nm) * 1e-3
        return np.polynomial.polynomial.polyval(x, self.coefficients)

    @classmethod
    def fit(cls, wavelengths_nm, delta_n, order: int = 2, reference_nm: float = 632.8) -> 'PolynomialCalibration':
        x = (np.asarray(wavelengths_nm, dtype=float) - reference_nm) * 1e-3
        return cls(np.polynomial.polynomial.polyfit(x, np.asarray(delta_n, dtype=float), order), reference_nm)


_REGISTRY: Dict[str, Callable[..., Calibration]] = {}


def register_calibration(kind: str, factory: Callable[..., Calibration]):
    """Make a new kind of calibration available to :func:`make_calibration`"""
    _REGISTRY[kind.lower()] = factory


def calibration_kinds():
    return list(_REGISTRY)


def make_calibration(kind: str, **kwargs) -> Calibration:
    """Factory of calibrations, see the module documentation"""
    try:
        return _REGISTRY[kind.lower()](**kwargs)
    except KeyError:
        raise ValueError(f'Unknown calibration {kind!r}, choose among {calibration_kinds()}') from None


register_calibration('single point', SinglePointCalibration)
register_calibration('sellmeier', SellmeierCalibration)
register_calibration('polynomial', PolynomialCalibration)

__all__ = ['Calibration', 'SinglePointCalibration', 'SellmeierCalibration', 'PolynomialCalibration',
           'register_calibration', 'calibration_kinds', 'make_calibration']
