import os, sys, glob
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for t in ("sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "trace_auditor"):
    sys.path.insert(0, os.path.join(REPO, "tools", t))
D = os.path.join(REPO, "testdata", "pherc_paris4_45um")
A_DIR = glob.glob(D + "/*w116-117.tifxyz")[0]
B_DIR = glob.glob(D + "/*w118-119.tifxyz")[0]
SLICES = os.path.join(D, "slices")
HEIGHTS = (2073, 2600, 3128)
VOX_UM = 45.532
