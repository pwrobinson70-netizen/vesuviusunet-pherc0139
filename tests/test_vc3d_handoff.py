"""vun-audit --vc3d-folder: a fake VC3D project (volume + patches from the concentric-ring phantom, one good and one with a
planted sheet switch). Verdicts land in each patch folder, the originals stay byte-identical, re-running is idempotent."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("zarr")
pytest.importorskip("scipy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "trace_auditor"))

import trace_auditor as ta  # noqa: E402
import vc3d_handoff as vh  # noqa: E402
from test_sheet_spacing_check import CX, CY, NZ, PITCH, R0, cylinder, make_ct  # noqa: E402
from test_trace_auditor import _write_mesh, hop_mesh  # noqa: E402


def _tree_hashes(root, skip=()):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob("*")) if p.is_file() and p.name not in skip}


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    import zarr
    root = tmp_path_factory.mktemp("vc3d_project")
    z = zarr.open(str(root / "volumes" / "ct.zarr"), mode="w", shape=(NZ, 640, 512), chunks=(1, 320, 256), dtype="f4")
    z[:] = make_ct(0.0)
    _write_mesh(root / "paths" / "good.tifxyz", cylinder(R0))
    _write_mesh(root / "paths" / "nested" / "switch.tifxyz", hop_mesh(R0, 300, PITCH))
    zs = list(range(0, NZ, 10))
    (root / "umb.json").write_text(json.dumps({"control_points": [{"z": z_, "y": CY, "x": CX} for z_ in zs]}))
    return root


ARGS = ["--heights", "30,50,70"]


def run(project):
    return ta.main(["--vc3d-folder", str(project), "--umbilicus", str(project / "umb.json"), *ARGS])


def test_verdicts_written_into_patches_and_originals_untouched(project):
    before = _tree_hashes(project)
    assert run(project) == 1                                           # one FAIL (the switch)
    good = json.loads((project / "paths" / "good.tifxyz" / "verdict.json").read_text())
    bad = json.loads((project / "paths" / "nested" / "switch.tifxyz" / "verdict.json").read_text())
    assert good["verdict"] == "PASS" and bad["verdict"] == "FAIL"
    assert good["patch"] == "paths/good.tifxyz" and good["heights"] == [30.0, 50.0, 70.0]
    assert any(c["check"] in ("switch_finder", "winding_jumps") and c["status"] == "FAIL" for c in bad["checks"])
    assert "FAIL" in (project / "paths" / "nested" / "switch.tifxyz" / "verdict.txt").read_text()
    summary = (project / "verdict_summary.txt").read_text()
    assert "paths/good.tifxyz" in summary and "paths/nested/switch.tifxyz" in summary and "1 PASS, 1 FAIL, 0 NOT JUDGED" in summary
    assert (project / "verdict_summary.csv").read_text().splitlines()[0] == "patch,verdict,judged_fraction,reasons"
    after = _tree_hashes(project)
    new = set(after) - set(before)
    assert new == {"paths/good.tifxyz/verdict.json", "paths/good.tifxyz/verdict.txt", "paths/nested/switch.tifxyz/verdict.json",
                   "paths/nested/switch.tifxyz/verdict.txt", "verdict_summary.txt", "verdict_summary.csv"}
    assert all(after[k] == before[k] for k in before)                  # x/y/z.tif, meta.json, the volume: byte-identical


def test_rerun_is_idempotent(project):
    run(project)
    first = _tree_hashes(project)
    run(project)
    assert _tree_hashes(project) == first


def test_no_volume_is_not_judged_not_a_crash(project, tmp_path):
    import shutil
    p = tmp_path / "p"
    shutil.copytree(project / "paths", p / "paths")
    assert ta.main(["--vc3d-folder", str(p), *ARGS]) == 4
    v = json.loads((p / "paths" / "good.tifxyz" / "verdict.json").read_text())
    assert v["verdict"] == "NOT JUDGED" and "no volume" in v["checks"][0]["reason"]


def test_volume_flag_and_meta_key(project, tmp_path):
    import shutil
    p = tmp_path / "p"
    shutil.copytree(project / "paths", p / "paths")
    vol = str(project / "volumes" / "ct.zarr")
    assert ta.main(["--vc3d-folder", str(p), "--volume", vol, "--umbilicus", str(project / "umb.json"), *ARGS]) == 1
    meta = p / "paths" / "good.tifxyz" / "meta.json"
    m = json.loads(meta.read_text())
    m["volume"] = vol
    meta.write_text(json.dumps(m))
    assert vh.volume_from_meta(str(p), str(p / "paths" / "good.tifxyz")) == vol


def test_bad_inputs(tmp_path, capsys):
    assert ta.main(["--vc3d-folder", str(tmp_path / "nope")]) == 2
    (tmp_path / "empty").mkdir()
    assert ta.main(["--vc3d-folder", str(tmp_path / "empty")]) == 2
    assert "no tifxyz patch" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:                               # the single-trace form still insists on its arguments
        ta.main(["somewhere"])
    assert e.value.code == 2


def test_bad_patch_is_reported_not_fatal(project, tmp_path):
    import shutil
    p = tmp_path / "p"
    shutil.copytree(project / "paths" / "good.tifxyz", p / "good.tifxyz")
    (p / "broken.tifxyz").mkdir()
    for n in ("x.tif", "y.tif", "z.tif"):
        (p / "broken.tifxyz" / n).write_bytes(b"not a tiff")
    (p / "broken.tifxyz" / "meta.json").write_text("{}")
    rc = ta.main(["--vc3d-folder", str(p), "--volume", str(project / "volumes" / "ct.zarr"), "--umbilicus", str(project / "umb.json"), *ARGS])
    assert rc == 4
    v = json.loads((p / "broken.tifxyz" / "verdict.json").read_text())
    assert v["verdict"] == "NOT JUDGED"
    assert json.loads((p / "good.tifxyz" / "verdict.json").read_text())["verdict"] == "PASS"


def test_ps1_is_crlf_with_utf8_bom_and_names_the_venv():
    b = (ROOT / "scripts" / "judge_patch.ps1").read_bytes()
    assert b.startswith(b"\xef\xbb\xbf")
    body = b[3:]
    assert body.count(b"\r\n") == body.count(b"\n") > 20 and b"\r" not in body.replace(b"\r\n", b"")
    body.decode("ascii")
    assert b"C:\\VesuviusUNET\\venv\\Scripts\\python.exe" in body and b"--vc3d-folder" in body and b"pip install -e" in body
