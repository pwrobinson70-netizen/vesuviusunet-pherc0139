# Ours (not part of upstream): make the vendored, unmodified upstream package importable for its own tests.
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
