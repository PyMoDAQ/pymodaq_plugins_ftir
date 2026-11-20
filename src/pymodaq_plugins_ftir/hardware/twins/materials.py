# -*- coding: utf-8 -*-
"""Birefringent materials of the TWINS wedges, described by their Sellmeier equations. Pure numpy.

New materials are made available with :func:`register_material`.
"""
from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np


@dataclass(frozen=True)
class SellmeierBirefringent:
    """Uniaxial crystal described by Sellmeier equations ``n^2 = A + B / (l^2 - C) - D l^2`` (l in µm)"""
    name: str
    ordinary: Tuple[float, float, float, float]
    extraordinary: Tuple[float, float, float, float]

    @staticmethod
    def _index(coeffs, wavelength_nm):
        a, b, c, d = coeffs
        l2 = (np.asarray(wavelength_nm, dtype=float) * 1e-3) ** 2
        return np.sqrt(a + b / (l2 - c) - d * l2)

    def n_o(self, wavelength_nm):
        return self._index(self.ordinary, wavelength_nm)

    def n_e(self, wavelength_nm):
        return self._index(self.extraordinary, wavelength_nm)

    def delta_n(self, wavelength_nm):
        """Birefringence ``n_o - n_e`` (positive for alpha-BBO, a negative uniaxial crystal)"""
        return self.n_o(wavelength_nm) - self.n_e(wavelength_nm)


#: alpha-BBO, Sellmeier coefficients as published by the crystal vendors (valid ~ 190 nm - 3.5 µm),
#: delta_n ~ 0.121 at 633 nm (the project report quotes 0.1225)
ALPHA_BBO = SellmeierBirefringent(name='alpha-BBO',
                                  ordinary=(2.67579, 0.02099, 0.00470, 0.00528),
                                  extraordinary=(2.31197, 0.01184, 0.01607, 0.00400))

MATERIALS: Dict[str, SellmeierBirefringent] = {}


def register_material(material: SellmeierBirefringent) -> SellmeierBirefringent:
    """Register a material (by its name) so that it can be found in the configuration and by the calibrations"""
    MATERIALS[material.name] = material
    return material


register_material(ALPHA_BBO)


__all__ = ['SellmeierBirefringent', 'ALPHA_BBO', 'MATERIALS', 'register_material']
