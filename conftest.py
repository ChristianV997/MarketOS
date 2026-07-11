"""Global pytest configuration.

Isolate all on-disk persistence into a throwaway temp directory so tests
never read or write the real ``state/`` directory. These env vars are set at
import time — before any application module computes its snapshot-path
constants — so every store persists into (and restores from) the temp dir,
keeping tests hermetic and free of cross-run pollution.
"""
import os
import tempfile

_TEST_STATE_DIR = tempfile.mkdtemp(prefix="marketos_test_state_")
os.environ["MARKETOS_STATE_DIR"] = _TEST_STATE_DIR
os.environ["PATTERNSTORE_PATH"] = os.path.join(_TEST_STATE_DIR, "patternstore.json")
