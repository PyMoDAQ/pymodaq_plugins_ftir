from typing import Union

from pymodaq_plugins_ftir.hardware.materials import ALPHA_BBO, MATERIALS, SellmeierBirefringent
from pymodaq_plugins_ftir.hardware.calibrations.calibration_factory import CalibrationBase, CalibrationFactory


@CalibrationFactory.register()
class SellmeierCalibration(CalibrationBase):
    """Trust the Sellmeier equations of the material"""
    usual_name = 'Sellmeier'
    params = [{'title': 'Material:', 'name': 'material', 'type': 'list', 'limits': list(MATERIALS),
               'value': ALPHA_BBO.name}]

    def __init__(self, material: Union[str, SellmeierBirefringent] = ALPHA_BBO):
        self.material = MATERIALS[material] if isinstance(material, str) else material

    def delta_n(self, wavelength_nm):
        return self.material.delta_n(wavelength_nm)
