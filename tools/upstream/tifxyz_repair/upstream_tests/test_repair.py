import json
from pathlib import Path

import numpy as np
import pytest
import tifffile

from tifxyz_repair.checks import validate_patch, worst_severity
from tifxyz_repair.core import compute_bbox, find_patches, load_patch
from tifxyz_repair.repair import repair_bbox


def make_patch(
    tmp: Path,
    name: str = "patch",
    shape=(20, 30),
    origin=(100.0, 200.0, 300.0),
    spacing=20.0,
    invalid_cells=(),
    bbox="auto",
    scale=(0.05, 0.05),
    extra_meta=None,
):
    """Write a synthetic planar tifxyz patch and return its path."""
    h, w = shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    x = origin[0] + xs * spacing
    y = origin[1] + ys * spacing
    z = np.full(shape, origin[2], dtype=np.float32)
    for r, c in invalid_cells:
        x[r, c] = y[r, c] = z[r, c] = -1.0
    d = tmp / name
    d.mkdir(parents=True)
    tifffile.imwrite(d / "x.tif", x.astype(np.float32))
    tifffile.imwrite(d / "y.tif", y.astype(np.float32))
    tifffile.imwrite(d / "z.tif", z.astype(np.float32))
    meta = {"format": "tifxyz", "scale": list(scale), "type": "seg", "uuid": name}
    if bbox == "auto":
        valid = x != -1
        meta["bbox"] = [
            [float(a[valid].min()) for a in (x, y, z)],
            [float(a[valid].max()) for a in (x, y, z)],
        ]
    elif bbox is not None:
        meta["bbox"] = bbox
    if extra_meta:
        meta.update(extra_meta)
    (d / "meta.json").write_text(json.dumps(meta, indent=4) + "\n")
    return d


def get(findings, check):
    return [f for f in findings if f["check"] == check]


class TestClean:
    def test_clean_patch_validates_ok(self, tmp_path):
        p = load_patch(make_patch(tmp_path))
        findings = validate_patch(p)
        assert worst_severity(findings) == "info"  # only the valid-fraction info line
        assert not get(findings, "bbox-stale")

    def test_bbox_matches_cpp_semantics_with_invalid_cells(self, tmp_path):
        # invalid cells must not influence the bbox
        d = make_patch(tmp_path, invalid_cells=[(0, 0), (19, 29)], bbox=None)
        p = load_patch(d)
        low, high = compute_bbox(p)
        # min x is still 100.0: (0,0) is invalid but (1,0) keeps x=100.0
        assert low[0] == pytest.approx(float(p.x[p.valid].min()))
        assert low[0] == pytest.approx(100.0)
        assert high[0] == pytest.approx(float(p.x[p.valid].max()))
        assert high[2] == pytest.approx(300.0)


class TestStaleBbox:
    def test_stale_bbox_detected(self, tmp_path):
        stale = [[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]]  # nowhere near the true extent
        d = make_patch(tmp_path, bbox=stale)
        findings = validate_patch(load_patch(d))
        f = get(findings, "bbox-stale")
        assert len(f) == 1
        assert f[0]["severity"] == "error"
        assert f[0]["frac_outside"] > 0.9
        assert f[0]["max_drift"] > 100

    def test_fix_recomputes_bbox(self, tmp_path):
        stale = [[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]]
        d = make_patch(tmp_path, bbox=stale)
        p = load_patch(d)
        change = repair_bbox(p)
        assert change and "recompute" in change
        meta = json.loads((d / "meta.json").read_text())
        low, high = meta["bbox"]
        assert low[0] == pytest.approx(100.0)
        assert high[0] == pytest.approx(100.0 + 29 * 20.0)
        assert (d / "meta.json.bak").exists()
        # now clean
        assert not get(validate_patch(load_patch(d)), "bbox-stale")
        # idempotent
        assert repair_bbox(load_patch(d)) is None

    def test_fix_dry_run_writes_nothing(self, tmp_path):
        stale = [[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]]
        d = make_patch(tmp_path, bbox=stale)
        before = (d / "meta.json").read_text()
        change = repair_bbox(load_patch(d), dry_run=True)
        assert change.startswith("[dry-run]")
        assert (d / "meta.json").read_text() == before

    def test_strip_bbox(self, tmp_path):
        d = make_patch(tmp_path)
        repair_bbox(load_patch(d), strip=True)
        assert "bbox" not in json.loads((d / "meta.json").read_text())

    def test_fix_preserves_other_fields(self, tmp_path):
        stale = [[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]]
        d = make_patch(tmp_path, bbox=stale, extra_meta={"custom_field": {"a": 1}})
        repair_bbox(load_patch(d))
        meta = json.loads((d / "meta.json").read_text())
        assert meta["custom_field"] == {"a": 1}
        assert meta["uuid"] == "patch"

    def test_missing_bbox_is_info_not_error(self, tmp_path):
        d = make_patch(tmp_path, bbox=None)
        findings = validate_patch(load_patch(d))
        f = get(findings, "bbox-missing")
        assert len(f) == 1 and f[0]["severity"] == "info"
        # fix must NOT invent a bbox when none was stored
        assert repair_bbox(load_patch(d)) is None


class TestDefects:
    def test_nan_vertices_flagged(self, tmp_path):
        d = make_patch(tmp_path)
        z = tifffile.imread(d / "z.tif")
        z[5, 5] = np.nan
        tifffile.imwrite(d / "z.tif", z)
        findings = validate_patch(load_patch(d))
        assert get(findings, "nan-vertices")

    def test_partial_sentinel_flagged(self, tmp_path):
        d = make_patch(tmp_path)
        y = tifffile.imread(d / "y.tif")
        y[3, 3] = -1.0  # x stays valid → inconsistent
        tifffile.imwrite(d / "y.tif", y)
        findings = validate_patch(load_patch(d))
        assert get(findings, "partial-sentinel")

    def test_all_invalid_is_error(self, tmp_path):
        h, w = 4, 4
        d = make_patch(tmp_path, shape=(h, w), invalid_cells=[(r, c) for r in range(h) for c in range(w)], bbox=None)
        findings = validate_patch(load_patch(d))
        assert get(findings, "no-valid-vertices")

    def test_shape_mismatch_is_error(self, tmp_path):
        d = make_patch(tmp_path)
        tifffile.imwrite(d / "y.tif", np.zeros((5, 5), dtype=np.float32))
        findings = validate_patch(load_patch(d))
        assert get(findings, "grid-shape")

    def test_bad_scale_is_error(self, tmp_path):
        d = make_patch(tmp_path, scale=(0.0, 0.05))
        findings = validate_patch(load_patch(d))
        assert get(findings, "meta-scale")

    def test_zero_voxelsize_is_error(self, tmp_path):
        d = make_patch(tmp_path, extra_meta={"voxelsize": 0})
        findings = validate_patch(load_patch(d))
        assert get(findings, "meta-voxelsize")

    def test_missing_meta_is_error(self, tmp_path):
        d = make_patch(tmp_path)
        (d / "meta.json").unlink()
        findings = validate_patch(load_patch(d))
        assert get(findings, "meta-parse")

    def test_corrupt_tif_is_error_not_crash(self, tmp_path):
        d = make_patch(tmp_path)
        (d / "x.tif").write_bytes(b"not a tiff")
        findings = validate_patch(load_patch(d))
        assert get(findings, "tif-read")


class TestLoaderSemantics:
    """The loader invalidates points before QuadSurface::bbox() runs; a bbox
    computed from `x != -1` alone over-counts and yields false positives."""

    def _write(self, d, x, y, z, bbox=None, mask=None):
        tifffile.imwrite(d / "x.tif", x.astype(np.float32))
        tifffile.imwrite(d / "y.tif", y.astype(np.float32))
        tifffile.imwrite(d / "z.tif", z.astype(np.float32))
        if mask is not None:
            tifffile.imwrite(d / "mask.tif", mask.astype(np.uint8))
        meta = {"format": "tifxyz", "scale": [0.05, 0.05], "type": "seg", "uuid": d.name}
        if bbox is not None:
            meta["bbox"] = bbox
        (d / "meta.json").write_text(json.dumps(meta, indent=4) + "\n")

    def test_z_nonpositive_is_invalid(self, tmp_path):
        d = make_patch(tmp_path, shape=(10, 10), bbox=None)
        z = tifffile.imread(d / "z.tif")
        z[0, :] = -5.0  # loader rewrites these to (-1,-1,-1)
        tifffile.imwrite(d / "z.tif", z)
        p = load_patch(d)
        assert not p.valid[0, :].any()
        assert p.valid[1:, :].all()
        assert compute_bbox(p)[0][2] == pytest.approx(300.0)

    def test_mask_excludes_points(self, tmp_path):
        d = tmp_path / "masked"
        d.mkdir()
        ys, xs = np.mgrid[0:10, 0:10].astype(np.float32)
        x, y, z = 100 + xs * 20, 200 + ys * 20, np.full((10, 10), 300.0, np.float32)
        mask = np.full((10, 10), 255, np.uint8)
        mask[:, 9] = 0  # last column masked out
        self._write(d, x, y, z, mask=mask)
        p = load_patch(d)
        assert not p.valid[:, 9].any()
        assert compute_bbox(p)[1][0] == pytest.approx(100 + 8 * 20)

    def test_mask_integer_upscale_is_decimated(self, tmp_path):
        d = tmp_path / "upscaled"
        d.mkdir()
        ys, xs = np.mgrid[0:8, 0:8].astype(np.float32)
        x, y, z = 100 + xs * 20, 200 + ys * 20, np.full((8, 8), 300.0, np.float32)
        mask = np.full((16, 16), 255, np.uint8)  # 2x the grid
        mask[:, 14:] = 0  # maps to grid column 7
        self._write(d, x, y, z, mask=mask)
        p = load_patch(d)
        assert not p.valid[:, 7].any()
        assert p.valid[:, :7].all()

    def test_mask_upscale_any_pixel_invalidates_block(self, tmp_path):
        """The loader walks every mask pixel and invalidates its (src // scale)
        grid cell, so one below-threshold pixel anywhere in a scale x scale
        block kills that vertex. Sampling a single pixel per block (plain
        striding) would keep vertices VC3D discards."""
        d = tmp_path / "block"
        d.mkdir()
        ys, xs = np.mgrid[0:8, 0:8].astype(np.float32)
        x, y, z = 100 + xs * 20, 200 + ys * 20, np.full((8, 8), 300.0, np.float32)
        mask = np.full((16, 16), 255, np.uint8)  # 2x the grid
        mask[0, 15] = 0  # only the second pixel of grid cell (0, 7)'s block
        self._write(d, x, y, z, mask=mask)
        p = load_patch(d)
        assert not p.valid[0, 7], "any masked pixel in the block must invalidate"
        assert p.valid[0, :7].all() and p.valid[1:, :].all()

    def test_mask_planar_separate_uses_channel0(self, tmp_path):
        """PLANARCONFIG_SEPARATE multi-channel masks come back from tifffile
        as (C, H, W); channel 0 must still be the mask plane."""
        d = tmp_path / "planar"
        d.mkdir()
        ys, xs = np.mgrid[0:10, 0:10].astype(np.float32)
        x, y, z = 100 + xs * 20, 200 + ys * 20, np.full((10, 10), 300.0, np.float32)
        mask = np.full((3, 10, 10), 255, np.uint8)  # (C, H, W)
        mask[0, :, 9] = 0  # channel 0 masks the last column
        tifffile.imwrite(d / "mask.tif", mask, planarconfig="separate", photometric="rgb")
        self._write(d, x, y, z)
        p = load_patch(d)
        assert not p.valid[:, 9].any()
        assert p.valid[:, :9].all()

    def test_no_false_positive_from_masked_outliers(self, tmp_path):
        """Regression for the exact bug this class documents: a patch whose
        stored bbox is correct under loader semantics must not be flagged
        just because masked/z<=0 outliers lie beyond it."""
        d = tmp_path / "regression"
        d.mkdir()
        ys, xs = np.mgrid[0:10, 0:10].astype(np.float32)
        x, y, z = 100 + xs * 20, 200 + ys * 20, np.full((10, 10), 300.0, np.float32)
        mask = np.full((10, 10), 255, np.uint8)
        # far-away outliers that the loader discards two different ways
        x[0, 0], y[0, 0] = 9999.0, 9999.0
        mask[0, 0] = 0
        x[9, 9], y[9, 9] = -9999.0, -9999.0
        z[9, 9] = -1.0
        true_bbox = [[100.0, 200.0, 300.0], [100 + 9 * 20.0, 200 + 9 * 20.0, 300.0]]
        self._write(d, x, y, z, bbox=true_bbox, mask=mask)
        findings = validate_patch(load_patch(d))
        assert not get(findings, "bbox-stale"), "correct bbox must not be reported stale"
        assert repair_bbox(load_patch(d)) is None, "must not rewrite a correct bbox"


class TestRobustness:
    def test_mismatched_grids_do_not_crash(self, tmp_path):
        """A truncated tif (mismatched grid shapes) must be reported, not
        crash validate/fix or abort the rest of a batch."""
        d = make_patch(tmp_path, name="broken")
        tifffile.imwrite(d / "z.tif", np.full((5, 5), 300.0, np.float32))
        p = load_patch(d)
        assert not p.valid.any()
        assert compute_bbox(p) is None
        assert repair_bbox(p, dry_run=True) is None  # must not raise
        findings = validate_patch(p)
        assert get(findings, "grid-shape")

    def test_fix_continues_past_corrupt_patch(self, tmp_path, capsys):
        from tifxyz_repair.cli import main

        broken = make_patch(tmp_path, name="a_broken", bbox=[[0, 0, 0], [1, 1, 1]])
        tifffile.imwrite(broken / "y.tif", np.zeros((3, 3), np.float32))
        make_patch(tmp_path, name="b_stale", bbox=[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
        code = main(["fix", str(tmp_path), "--dry-run"])
        out = capsys.readouterr().out
        assert "b_stale" in out, "later patches must still be processed"
        assert code in (0, 1)

    def test_nonexistent_path_exits_2(self, tmp_path, capsys):
        from tifxyz_repair.cli import main

        assert main(["validate", str(tmp_path / "no_such_dir")]) == 2
        assert main(["fix", str(tmp_path / "no_such_dir"), "--dry-run"]) == 2
        err = capsys.readouterr().err
        assert "does not exist" in err

    def test_empty_dir_exits_2(self, tmp_path):
        from tifxyz_repair.cli import main

        (tmp_path / "empty").mkdir()
        assert main(["validate", str(tmp_path / "empty")]) == 2

    def test_non_ascii_meta_reads_as_utf8(self, tmp_path):
        """meta.json is JSON, hence UTF-8; the locale encoding must not
        matter (Windows cp1252 boxes read it identically)."""
        d = make_patch(tmp_path, extra_meta={"source": "PHercParis4 – trémie"})
        p = load_patch(d)
        assert p.meta_error is None
        assert p.meta["source"] == "PHercParis4 – trémie"
        assert repair_bbox(p, dry_run=True) is None  # bbox is correct


class TestDiscovery:
    def test_find_patches_nested(self, tmp_path):
        make_patch(tmp_path / "a", name="p1")
        make_patch(tmp_path / "b" / "c", name="p2")
        found = find_patches(tmp_path)
        assert len(found) == 2

    def test_find_patches_direct(self, tmp_path):
        d = make_patch(tmp_path)
        assert find_patches(d) == [d]


class TestDeep:
    def test_inspect_clean_patch(self, tmp_path):
        pytest.importorskip("scipy")
        from tifxyz_repair.deep import inspect_patch

        d = make_patch(tmp_path, shape=(30, 30))
        m = inspect_patch(load_patch(d))
        assert m["holes"]["count"] == 0
        assert m["spacing"]["median"] == pytest.approx(20.0)
        assert m["self_proximity"]["pairs"] == 0

    def test_inspect_detects_interior_hole(self, tmp_path):
        pytest.importorskip("scipy")
        from tifxyz_repair.deep import inspect_patch

        d = make_patch(tmp_path, shape=(30, 30), invalid_cells=[(10, 10), (10, 11)])
        m = inspect_patch(load_patch(d))
        assert m["holes"]["count"] == 1
        assert m["holes"]["cells"] == 2

    def test_inspect_detects_sheet_switch(self, tmp_path):
        pytest.importorskip("scipy")
        from tifxyz_repair.deep import inspect_patch

        # Fold the right half back over the left: distant columns land at
        # identical 3D positions — the sheet-switch signature.
        d = make_patch(tmp_path, shape=(20, 40))
        x = tifffile.imread(d / "x.tif")
        x[:, 20:] = x[:, 19::-1]
        tifffile.imwrite(d / "x.tif", x.astype(np.float32))
        m = inspect_patch(load_patch(d))
        assert m["self_proximity"]["pairs"] > 0


def make_defective_patch(tmp: Path) -> Path:
    """Synthetic patch with all three exportable defect families: a sheet
    switch (folded right half), an interior hole, and a stretched vertex."""
    d = make_patch(tmp, shape=(30, 40))
    x = tifffile.imread(d / "x.tif")
    y = tifffile.imread(d / "y.tif")
    z = tifffile.imread(d / "z.tif")
    x[:, 20:] = x[:, 19::-1]  # fold → self-proximity suspects
    for r, c in ((10, 10), (10, 11)):  # interior hole
        x[r, c] = y[r, c] = z[r, c] = -1.0
    z[20, 5] += 200.0  # strongly stretched vertex
    z[5, 30] += 50.0  # mildly stretched vertex
    tifffile.imwrite(d / "x.tif", x.astype(np.float32))
    tifffile.imwrite(d / "y.tif", y.astype(np.float32))
    tifffile.imwrite(d / "z.tif", z.astype(np.float32))
    return d


class TestPointsetExport:
    """Round-trip the export against the schema PointCollections::loadFromJSON
    parses (villa/volume-cartographer core/src/PointCollections.cpp)."""

    def test_export_matches_vc3d_schema(self, tmp_path):
        pytest.importorskip("scipy")
        from tifxyz_repair.deep import defect_points, export_pointset, inspect_patch

        d = make_defective_patch(tmp_path)
        patch = load_patch(d)
        metrics = inspect_patch(patch, collect_cells=True)
        cells = metrics["defect_cells"]
        assert cells["self_proximity"] and cells["hole_boundary"] and cells["stretch"]
        # hole cells themselves are invalid → only their valid ring is exported
        assert [10, 10] not in cells["hole_boundary"]
        assert [10, 9] in cells["hole_boundary"]
        # stretch cells are exactly the endpoints of the over-threshold edges,
        # worst edge first: every cell of the 200-voxel spike sorts before any
        # cell of the 50-voxel one
        big = {(20, 4), (20, 5), (20, 6), (19, 5), (21, 5)}
        small = {(5, 29), (5, 30), (5, 31), (4, 30), (6, 30)}
        stretch = [tuple(rc) for rc in cells["stretch"]]
        assert set(stretch) == big | small
        assert set(stretch[: len(big)]) == big

        out = tmp_path / "defects.json"
        export_pointset([(d.name, defect_points(patch, metrics))], out)
        data = json.loads(out.read_text())

        # top level: loadFromJSON requires the version key to be the *string*
        # "1" (PointCollections.cpp:590) and "collections" to be an object
        # keyed by stringified uint64 ids (:598-604)
        assert data["vc_pointcollections_json_version"] == "1"
        assert isinstance(data["vc_pointcollections_json_version"], str)
        assert isinstance(data["collections"], dict)

        names = set()
        all_point_ids = []
        for cid, col in data["collections"].items():
            int(cid)  # must parse per stoull
            # required collection fields (PointCollections.cpp:147-161)
            assert isinstance(col["name"], str)
            assert isinstance(col["points"], dict)
            assert isinstance(col["metadata"], dict)
            assert isinstance(col["metadata"]["winding_is_absolute"], bool)
            assert len(col["color"]) == 3
            assert all(0.0 <= v <= 1.0 for v in col["color"])
            names.add(col["name"])
            for pid, pt in col["points"].items():
                int(pid)
                all_point_ids.append(pid)
                # required point field "p" = [x, y, z] (PointCollections.cpp:59)
                assert len(pt["p"]) == 3
                assert all(isinstance(v, float) for v in pt["p"])
                assert pt["wind_a"] is None
                assert isinstance(pt["creation_time"], int)
        # point ids must be unique across all collections (loader rebuilds a
        # flat id→point map, PointCollections.cpp:633-639)
        assert len(all_point_ids) == len(set(all_point_ids))
        assert names == {
            f"defect_switch_{d.name}",
            f"defect_hole_{d.name}",
            f"defect_stretch_{d.name}",
        }

        # coordinate order: a known suspect cell's grid values must appear as
        # (x, y, z) — make_patch encodes col in x, row in y, constant z
        r, c = cells["self_proximity"][0]
        expected_p = [float(patch.x[r, c]), float(patch.y[r, c]), float(patch.z[r, c])]
        switch = next(v for v in data["collections"].values() if v["name"] == f"defect_switch_{d.name}")
        assert expected_p in [pt["p"] for pt in switch["points"].values()]

    def test_export_caps_points(self, tmp_path):
        pytest.importorskip("scipy")
        from tifxyz_repair.deep import defect_points, export_pointset, inspect_patch

        d = make_defective_patch(tmp_path)
        patch = load_patch(d)
        metrics = inspect_patch(patch, collect_cells=True)
        data = export_pointset([(d.name, defect_points(patch, metrics))], tmp_path / "o.json", max_points=5)
        assert all(len(c["points"]) <= 5 for c in data["collections"].values())

    def test_cli_export_pointset(self, tmp_path, capsys):
        pytest.importorskip("scipy")
        from tifxyz_repair.cli import main

        d = make_defective_patch(tmp_path)
        out = tmp_path / "pointset.json"
        assert main(["inspect", str(d), "--export-pointset", str(out)]) == 0
        data = json.loads(out.read_text())
        assert data["vc_pointcollections_json_version"] == "1"
        assert any(c["name"].startswith("defect_switch_") for c in data["collections"].values())
        # printed metrics stay clean JSON without the cell dump
        printed = capsys.readouterr().out
        assert "defect_cells" not in printed


class TestCli:
    def test_cli_validate_exit_codes(self, tmp_path, capsys):
        from tifxyz_repair.cli import main

        clean = make_patch(tmp_path / "clean")
        assert main(["validate", str(clean)]) == 0
        stale = make_patch(tmp_path / "stale", bbox=[[0, 0, 0], [1, 1, 1]])
        assert main(["validate", str(stale)]) == 1

    def test_cli_report(self, tmp_path, capsys):
        from tifxyz_repair.cli import main

        make_patch(tmp_path / "t" / "a", name="p1")
        make_patch(tmp_path / "t" / "b", name="p2", bbox=[[0, 0, 0], [1, 1, 1]])
        csv_out = tmp_path / "audit.csv"
        rc = main(["report", str(tmp_path / "t"), "--csv", str(csv_out), "--workers", "1"])
        assert rc == 1  # one patch has an error
        out = capsys.readouterr().out
        assert "Stale bboxes" in out
        assert csv_out.exists()

    def test_cli_json_output(self, tmp_path, capsys):
        from tifxyz_repair.cli import main

        clean = make_patch(tmp_path)
        assert main(["validate", str(clean), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data[0]["status"] in ("ok", "info")


class TestNanSemantics:
    def test_nan_z_stays_valid_like_cpp(self, tmp_path):
        """C++ tests `z <= 0`; IEEE says NaN <= 0 is false, so the loader
        keeps NaN-z points. We must match, or we silently drop them."""
        d = make_patch(tmp_path, shape=(6, 6), bbox=None)
        z = tifffile.imread(d / "z.tif")
        z[2, 2] = np.nan
        tifffile.imwrite(d / "z.tif", z)
        p = load_patch(d)
        assert p.valid[2, 2], "NaN z must remain valid (matches C++ comparison)"
        assert get(validate_patch(p), "nan-vertices")
