"""Path setup for the ink_infer tests (kept inside the tool so repo-level CI is untouched)."""
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent
ROOT = TOOL.parent.parent
for p in (str(ROOT), str(TOOL)):
    if p not in sys.path:
        sys.path.insert(0, p)
