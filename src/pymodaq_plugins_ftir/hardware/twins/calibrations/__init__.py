"""One module per calibration, each registering its class with ``@CalibrationFactory.register()``.

Every module of this folder is imported automatically: to add a calibration, drop a new module here (see
``twins/calibration_factory.py`` for the factory and the base class)."""
import importlib
import pkgutil

for _module in pkgutil.iter_modules(__path__):
    importlib.import_module(f'{__name__}.{_module.name}')
