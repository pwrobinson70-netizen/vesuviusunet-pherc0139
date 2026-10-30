"""
run_hygiene.py -- REV 2 -- small, dependency-free additions for an overnight training run.
Save on the PC as vesuvius_unet/run_hygiene.py (module name stays stable; the revision
lives in __revision__ and is printed in the banner).
Import from train.py (or paste the four functions in). Nothing here changes the model,
the loss, or the data; it changes what tonight's run can PROVE tomorrow.

    from vesuvius_unet.run_hygiene import (print_run_banner, atomic_write_json,
                                           save_epoch_checkpoint, build_contract)

1. print_run_banner(...)   - first lines of the log: fix-set version, sha256 of every
                              source file, args, seed, split geometry, ink fractions.
                              A queued process imports whatever is on disk at launch;
                              the banner is how the log proves WHICH code ran.
2. build_contract(...)     - the training contract (aggregation, loss, depth window,
                              split geometry, normalisation) stored inside every
                              checkpoint so tune_threshold / infer can refuse a mismatch.
3. save_epoch_checkpoint() - one checkpoint PER EPOCH (~1.3 MB each at 334K params),
                              plus last.pt. Tomorrow, tune_threshold over every epoch
                              gives the true curve instead of trusting the selection
                              logic in #17.
4. atomic_write_json()     - history.json written to a temp file then os.replace'd, so
                              a kill mid-write cannot truncate it.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

FIX_SET_VERSION = "2026-09-19-fixes-18-19"  # bump whenever staged files change
__revision__ = "rev2"  # rev1 initial; rev2: split+val_fraction in contract check, contract mandatory, injectable saver
# fix_set bumped 2026-09-19 IN THE SAME CHANGE that deploys #18/#19, never in anticipation.


def sha256_file(path: str | os.PathLike, n: int = 12) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def print_run_banner(source_files, args=None, seed=None, extra: dict | None = None,
                     out=sys.stdout) -> dict:
    """Print (and return) a banner that pins down exactly what is running.
    source_files: iterable of paths (dataset.py, model.py, losses.py, train.py, ...).
    extra: e.g. {"split": roles.summary(), "train_ink_frac": 0.031, "val_ink_frac": 0.028}
    """
    info = {
        "fix_set": FIX_SET_VERSION,
        "run_hygiene_revision": __revision__,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cwd": os.getcwd(),
        "seed": seed,
        "files": {str(p): sha256_file(p) for p in source_files if Path(p).exists()},
        "args": vars(args) if args is not None and hasattr(args, "__dict__") else args,
    }
    try:
        import torch  # optional
        info["torch"] = torch.__version__
        info["cuda"] = torch.cuda.is_available()
    except Exception:  # pragma: no cover
        pass
    if extra:
        info.update(extra)
    line = "=" * 72
    print(line, file=out)
    print(f"RUN BANNER  fix_set={info['fix_set']}  run_hygiene={__revision__}  started={info['started']}", file=out)
    for k, v in info["files"].items():
        print(f"  {v}  {k}", file=out)
    for k in ("seed", "torch", "cuda", "args"):
        if k in info and info[k] is not None:
            print(f"  {k}: {info[k]}", file=out)
    for k, v in (extra or {}).items():
        print(f"  {k}: {v}", file=out)
    print(line, file=out, flush=True)
    return info


def build_contract(*, aggregation: str, topk: int | None, loss: str, alpha: float | None,
                   beta: float | None, depth_start: int, depth: int, patch_size: int,
                   split: dict, normalisation: str, val_fraction: float) -> dict:
    """Everything a scoring script must match to compare checkpoints fairly.
    split: e.g. {"kind": "buffered_bands", "val_band_cols": 4, "buffer_cols": 1}
           or   {"kind": "every_nth_column", "n": 5}  (the current live split)"""
    return {
        "contract_version": 1,
        "aggregation": aggregation,          # "max" | "topk_mean"
        "topk": topk,
        "loss": loss,                        # "bce_dice" | "bce_tversky"
        "tversky_alpha": alpha, "tversky_beta": beta,
        "depth_start": depth_start, "depth": depth, "patch_size": patch_size,
        "split": split, "val_fraction": val_fraction,
        "normalisation": normalisation,      # e.g. "per_fragment_zscore" | "none"
        "fix_set": FIX_SET_VERSION,
    }


CONTRACT_KEYS = ("aggregation", "topk", "depth_start", "depth", "patch_size",
                 "normalisation", "split", "val_fraction")


def assert_contract_matches(ckpt_contract: dict, runtime_contract: dict,
                            keys=CONTRACT_KEYS) -> None:
    """Call in tune_threshold / infer before scoring. Loss may differ (it is a
    training-time choice); aggregation, depth window, normalisation and SPLIT GEOMETRY
    may not - a checkpoint scored on a different split is a different experiment.
    `split` is compared as a whole dict, so both sides must build it the same way."""
    bad = {k: (ckpt_contract.get(k), runtime_contract.get(k))
           for k in keys if ckpt_contract.get(k) != runtime_contract.get(k)}
    if bad:
        raise RuntimeError(
            "checkpoint/runtime contract mismatch (checkpoint vs runtime): "
            + ", ".join(f"{k}={a!r} vs {b!r}" for k, (a, b) in bad.items())
            + ". Scoring this checkpoint under different settings compares different "
              "models, not the same model twice.")


def atomic_write_json(path: str | os.PathLike, obj) -> None:
    """Write JSON so a kill mid-write leaves the previous file intact."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic on Windows and POSIX


def save_epoch_checkpoint(run_dir: str | os.PathLike, epoch: int, payload: dict,
                          keep_every: int = 1, saver=None) -> Path | None:
    """Save epochNNN.pt every `keep_every` epochs (default: every epoch) and always
    refresh last.pt, both written atomically (tmp + os.replace).

    `payload` is your existing checkpoint dict and MUST already contain a "contract"
    key (see build_contract). This function does not invent one: a missing contract is
    a setup mistake, and defaulting it silently would hide exactly the error
    assert_contract_matches exists to catch, so it raises instead.

    `saver(obj, path)` defaults to torch.save; it is injectable so the control flow can
    be tested with a real byte-writing saver where torch is not installed.
    Returns the epoch path written, or None if this epoch was skipped."""
    if "contract" not in payload or not isinstance(payload["contract"], dict):
        raise ValueError("checkpoint payload has no 'contract' dict - build it with "
                         "build_contract() and add it before saving")
    if saver is None:
        import torch
        saver = torch.save
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("epoch", epoch)

    def _atomic(path: Path):
        tmp = path.with_suffix(path.suffix + ".tmp")
        saver(payload, tmp)
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise IOError(f"saver wrote nothing to {tmp}")
        os.replace(tmp, path)

    _atomic(run_dir / "last.pt")
    if epoch % keep_every == 0:
        p = run_dir / f"epoch{epoch:03d}.pt"
        _atomic(p)
        return p
    return None


if __name__ == "__main__":
    # self-test: banner prints, contract mismatch is caught, atomic write survives, no torch needed
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "x.py"; src.write_text("print(1)\n")
        info = print_run_banner([src], args={"lr": 1e-3}, seed=0,
                                extra={"split": "every_nth_column n=5 (live)", "val_ink_frac": 0.03})
        assert info["files"][str(src)] == sha256_file(src)
        c1 = build_contract(aggregation="topk_mean", topk=16, loss="bce_tversky", alpha=0.7, beta=0.3,
                            depth_start=0, depth=64, patch_size=64,
                            split={"kind": "every_nth_column", "n": 5}, normalisation="none", val_fraction=0.2)
        c2 = dict(c1, aggregation="max", topk=None)
        assert_contract_matches(c1, c1)
        try:
            assert_contract_matches(c1, c2); raise SystemExit("aggregation mismatch not caught")
        except RuntimeError as e:
            assert "aggregation" in str(e)
        # the case that matters most in this project: same everything, different split
        c3 = dict(c1, split={"kind": "buffered_bands", "val_band_cols": 4, "buffer_cols": 1})
        try:
            assert_contract_matches(c1, c3); raise SystemExit("split mismatch not caught")
        except RuntimeError as e:
            assert "split" in str(e)
        print("[ok] contract check catches aggregation AND split mismatches")
        hist = Path(d) / "history.json"
        atomic_write_json(hist, {"epochs": [1, 2]}); atomic_write_json(hist, {"epochs": [1, 2, 3]})
        assert json.loads(hist.read_text())["epochs"] == [1, 2, 3] and not hist.with_suffix(".json.tmp").exists()
        # checkpoint helper: exercised with a REAL byte-writing saver whether or not torch exists
        import pickle
        def pickle_saver(obj, path):
            with open(path, "wb") as f:
                pickle.dump(obj, f)
        try:
            save_epoch_checkpoint(d, 1, {"model": {"w": [0, 0, 0]}}, saver=pickle_saver)
            raise SystemExit("missing contract not caught")
        except ValueError as e:
            assert "contract" in str(e)
        p = save_epoch_checkpoint(d, 7, {"model": {"w": [0, 0, 0]}, "contract": c1}, saver=pickle_saver)
        assert p is not None and p.name == "epoch007.pt" and (Path(d) / "last.pt").exists()
        assert not (Path(d) / "last.pt.tmp").exists() and not (Path(d) / "epoch007.pt.tmp").exists()
        with open(p, "rb") as f:
            back = pickle.load(f)
        assert back["epoch"] == 7 and back["contract"] == c1
        assert save_epoch_checkpoint(d, 8, {"model": {}, "contract": c1}, keep_every=5, saver=pickle_saver) is None
        assert save_epoch_checkpoint(d, 10, {"model": {}, "contract": c1}, keep_every=5, saver=pickle_saver).name == "epoch010.pt"
        print("[ok] checkpoint per epoch + last.pt, atomic, contract mandatory, keep_every honoured")
        try:
            import torch
            p = save_epoch_checkpoint(d, 11, {"model": {"w": torch.zeros(3)}, "contract": c1})
            assert torch.load(p)["epoch"] == 11
            print("[ok] same path with torch.save")
        except ImportError:
            print("[note] torch not installed here; default saver (torch.save) exercised on the PC")
    print("[ok] banner, contract check, atomic json")
