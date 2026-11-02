import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "sheet_spacing_check"

# repo root (vesuvius_unet package) and the sheet_spacing_check tool modules
for p in (str(ROOT), os.path.normpath(str(TOOL))):
    if p not in sys.path:
        sys.path.insert(0, p)
