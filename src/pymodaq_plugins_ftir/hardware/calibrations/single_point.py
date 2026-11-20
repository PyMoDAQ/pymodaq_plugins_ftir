from typing import Optional

import numpy as np

from pymodaq_plugins_ftir.hardware.materials import ALPHA_BBO, SellmeierBirefringent
from pymodaq_plugins_ftir.hardware.calibrations.calibration_factory import CalibrationBase, CalibrationFactory


@CalibrationFactory.register()
class SinglePointCalibration(CalibrationBase):
    """One calibration point (a laser line): ``delta_n`` known at ``wavelength_nm``, constant elsewhere"""
    usual_name = 'Single point'
    params = [
        {'title': 'Wavelength:', 'name': 'wavelength_nm', 'type': 'float', 'value': 632.8, 'suffix': 'nm'},
        {'title': 'Delta n:', 'name': 'delta_n', 'type': 'float', 'value': 0.1212},
    ]

    def __init__(self, wavelength_nm: float = 632.8, delta_n: Optional[float] = None,
                 material: SellmeierBirefringent = ALPHA_BBO):
        """``delta_n`` defaults to the one of ``material`` at the calibration wavelength"""
        self.wavelength_nm = float(wavelength_nm)
        self.value = float(material.delta_n(wavelength_nm) if delta_n is None else delta_n)

    def delta_n(self, wavelength_nm):
        return np.full(np.shape(wavelength_nm), self.value)
