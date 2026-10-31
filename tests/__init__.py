"""Headless tests. Run with ``python -m unittest discover -s tests -t .``

Everything is pointed at a throwaway ``AUDIX_HOME`` before audix is imported, so a
test run can never touch a real queue, history, or cookie jar.
"""
import os
import tempfile

os.environ["AUDIX_HOME"] = tempfile.mkdtemp(prefix="audix-tests-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
