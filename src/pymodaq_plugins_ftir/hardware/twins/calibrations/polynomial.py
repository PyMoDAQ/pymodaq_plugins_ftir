from typing import Sequence

import numpy as np

from pymodaq_plugins_ftir.hardware.twins.calibration_factory import CalibrationBase, CalibrationFactory


@CalibrationFactory.register()
class PolynomialCalibration(CalibrationBase):
    """Custom polynomial ``delta_n = sum c_i x^i`` with ``x = (l - reference_nm) / 1000`` (µm), lowest order first.
    Coefficients can be fitted on known lines with :meth:`fit`."""
    usual_name = 'Polynomial'
    params = [
        {'title': 'Reference wavelength:', 'name': 'reference_nm', 'type': 'float', 'value': 632.8, 'suffix': 'nm'},
        {'title': 'Coefficients (lowest order first):', 'name': 'coefficients', 'type': 'str',
         'value': '0.1212, -0.02'},
    ]

    def __init__(self, coefficients: Sequence[float], reference_nm: float = 632.8):
        self.coefficients = np.asarray(coefficients, dtype=float)
        self.reference_nm = float(reference_nm)

    def delta_n(self, wavelength_nm):
        x = (np.asarray(wavelength_nm, dtype=float) - self.reference_nm) * 1e-3
        return np.polynomial.polynomial.polyval(x, self.coefficients)

    @classmethod
    def fit(cls, wavelengths_nm, delta_n, order: int = 2, reference_nm: float = 632.8) -> 'PolynomialCalibration':
        """Polynomial fitted on the birefringence measured at known wavelengths"""
        x = (np.asarray(wavelengths_nm, dtype=float) - reference_nm) * 1e-3
        return cls(np.polynomial.polynomial.polyfit(x, np.asarray(delta_n, dtype=float), order), reference_nm)
