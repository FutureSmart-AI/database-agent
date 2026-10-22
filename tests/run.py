"""Run focused backend regressions on the host or in the API container."""
from pathlib import Path
import subprocess
import sys
import unittest

root = Path(__file__).resolve().parents[1]
backend = root / "backend"
if backend.is_dir():
    sys.path.insert(0, str(backend))
suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent / "backend"))
result = unittest.TextTestRunner(verbosity=1).run(suite)
if not result.wasSuccessful():
    raise SystemExit(1)
subprocess.run([sys.executable, str(Path(__file__).parent / "backend/test_table_access_guard.py")], check=True)
