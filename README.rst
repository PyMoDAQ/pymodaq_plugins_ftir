pymodaq_plugins_ftir
####################

.. image:: https://img.shields.io/pypi/v/pymodaq_plugins_ftir.svg
   :target: https://pypi.org/project/pymodaq_plugins_ftir/
   :alt: Latest Version

PyMoDAQ plugins of the birefringent (TWINS) Fourier transform spectrometer of CEMES: a delay line made of alpha-BBO
wedges moved by a SmarAct linear piezo stage, two monitor photodiodes and their amplified difference digitised by an
acquisition card. This package targets **PyMoDAQ 5.3.x** (Python 3.10 to 3.13).

It contains a complete simulation of the setup, so that the FTIR extension can be developed without the hardware.

Authors
=======

* Sebastien Weber  (sebastien.weber@cemes.fr)

Instruments
===========

Actuators
+++++++++

* **FTIRStageSim**: simulated delay stage (SmarAct SLC like, positions in mm, finite velocity, real time)

Viewer0D
++++++++

* **FTIRCardSim**: simulated acquisition card, mean of the acquired samples for each channel (step by step scans)

Viewer1D
++++++++

* **FTIRCardSim**: simulated acquisition card (MCC 128 like, 16 bits): Monitor +, Monitor - and amplified difference
  against time

The real stage is driven by ``DAQ_Move_SmarActSCUAscii`` of `pymodaq_plugins_smaract
<https://github.com/PyMoDAQ/pymodaq_plugins_smaract>`_ (same units as the simulated one, mm).


The simulation
==============

``pymodaq_plugins_ftir.hardware.twins_simulator`` is pure numpy (no Qt, no PyMoDAQ), it can also be used from a
script or a notebook:

* ``TwinsOptics``: light source (HeNe, sodium doublet, LEDs, white light...), TWINS wedges in alpha-BBO (Sellmeier
  equations, so the position to delay conversion depends on the wavelength, as on the real setup) and balanced
  detection (``I+-(x) = 1/2 int S(l) [1 +- V cos(2 pi dn(l) e(x) / l)] dl``, ``e(x) = (x - x0) tan(apex angle)``),
  with offset, electronic noise and source intensity noise/drift (removed by the difference channel);
* ``SimulatedStage``: the stage moves at constant velocity in real time, its trajectory is known at any time;
* ``SimulatedAcquisitionCard``: acquires ``n`` samples at a given rate (blocking for ``n / rate`` seconds) at the
  positions taken by the stage meanwhile, digitised on 16 bits;
* ``get_bench()``: the bench shared by the plugins of a process, so that the card sees the stage of the actuator
  plugin. The default values come from the ``simulation`` section of the configuration file of the package
  (``config_ftir.toml`` in the PyMoDAQ user configuration folder). The geometry of the TWINS (apex angle of the
  wedges, 15°, and their length, 25 mm, as on the CEMES setup; position of the wedge centre; zero delay position, which
  depends on the fixed plate and on the mounting of the stage) can also be changed in the settings of the stage
  plugin. The beam crosses the moving wedge on 25 mm of stage travel only: the signal vanishes outside.

A continuous scan as the extension will do it: in a Dashboard with ``FTIRStageSim`` and ``FTIRCardSim`` (1D),
move the stage to the start position, start a move to the end position and grab the card while it moves (with the
``Export stage positions`` option, the true positions are emitted too, to check the analysis).

From a script, without any GUI::

    import numpy as np
    from pymodaq_plugins_ftir.hardware.twins_simulator import (TwinsFTIRBench, TwinsOptics, SimulatedStage,
                                                               VirtualClock, spectrum_from_interferogram)

    bench = TwinsFTIRBench(TwinsOptics(), SimulatedStage(clock=VirtualClock()))  # virtual clock: no waiting
    bench.set_source('Sodium doublet (589.0/589.6 nm)')
    result = bench.scan(start_um=-12000, stop_um=12000, rate_hz=5000)
    delay_fs = bench.optics.delay_fs(result.positions_um, wavelength_nm=632.8)
    wavelength_nm, spectrum = spectrum_from_interferogram(delay_fs, result.data['diff'])

``spectrum_from_interferogram`` converts the delay with a single birefringence (calibration at one wavelength), so
the lines are shifted away from it (about -4 % at 450 nm and +3 % at 1000 nm for alpha-BBO).
``spectrum_from_interferogram_dispersive`` uses the Sellmeier equations instead (``delta_n(l)``), with a calibrated
thickness axis (one calibration point with a laser): the lines are then recovered to better than 1 nm *in the
simulation*, which uses the same equations. On the real setup the accuracy is limited by the one of the Sellmeier
coefficients of the wedges and by the calibration.

Calibrations
------------

``pymodaq_plugins_ftir.hardware.calibration`` gives the law ``delta_n(l)`` used to convert a thickness difference to a
wavelength, chosen with a factory (``make_calibration``), each one having a ``spectrum(thickness_nm, signal)`` method::

    from pymodaq_plugins_ftir.hardware.calibration import make_calibration, PolynomialCalibration

    make_calibration('single point', wavelength_nm=632.8, delta_n=0.1212)   # one laser line, dispersion ignored
    make_calibration('sellmeier')                                           # trust the Sellmeier equations
    PolynomialCalibration.fit(known_lines_nm, measured_delta_n, order=3)    # custom polynomial, fitted on known lines

Other kinds are added with ``register_calibration(name, factory)``.

Not simulated: spectral response of the photodiodes, transmission of the optics, acceleration ramps and closed loop
jitter of the stage, bandwidth of the amplifier.


Installation instructions
=========================

* PyMoDAQ 5.3.x, any operating system (the simulated plugins need no driver).
* ``pip install pymodaq_plugins_ftir``

The plugins of the historical setup (NI DAQmx card driven by ``pymodaq_plugins_daqmx`` < 5, ``Diodes`` and
``Autoco``) and the PyMoDAQ 4 analysis application ``ftir.py`` do not work with PyMoDAQ 5.3: they are kept, for
reference, in ``docs/legacy``.


Development
===========

* Install the plugin in editable mode: ``pip install -e .``
* Check it, without any hardware: ``check_plugin`` and ``pytest``
* If you use an AI coding assistant, point it to ``AGENTS.md``: it describes the patterns to follow for instrument
  plugins and Dashboard extensions (``CustomExt``, the FTIR extension to come).
