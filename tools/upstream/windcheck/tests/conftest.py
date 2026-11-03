# Ours (not part of upstream): build windcheck's C++ engine before upstream's test_selfcross.py is collected (it skips if the binary
# is missing).  Needs g++ or clang++; without one the upstream tests skip, as they do upstream.
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import ct_aware_check  # noqa: E402

ct_aware_check.build_engine()
