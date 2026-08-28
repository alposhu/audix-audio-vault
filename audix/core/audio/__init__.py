"""Audio subsystem: decoding, peak analysis, DSP, playback, and measurement.

Deliberately Qt-free. Everything here takes plain callbacks and can be driven
from a worker thread, a test, or a CLI.
"""
