#!/usr/bin/env python3
"""run_grid: the full calibration grid -> one CSV (MIT).

    python tools/calibration/run_grid.py --out tools/calibration/results/grid.csv --jobs 4

Grid (flags): --seeds 0-19  --steps 2,5,10,20 (tifxyz grid step, voxels)  --pitches 8,15,30,60 (sheet pitch, voxels)
--deforms round,mild,crushed,merged  --size 192. One task = one (seed, pitch, deformation): the volume is rendered once
(cached under --cache, .npz), then every grid step is evaluated on it. Tasks run in parallel (--jobs); rows are appended to
the CSV as tasks finish and the finished tasks are listed in <out>.done, so an interrupted run continues where it stopped
(--resume, the default; --fresh starts over). Columns: see calib.COLUMNS. Runtime: roughly 2 h on 4 cores for the full grid.
"""
from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import calib  # noqa: E402


def parse_list(s, cast=float):
    out = []
    for part in str(s).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part and cast is int and not part.startswith("-"):
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(cast(part))
    return out


def _work(args):
    seed, pitch, deform, steps, size, cache, cfg = args
    t0 = time.time()
    try:
        rows = calib.evaluate_phantom(seed, pitch, deform, steps, size, cache, cfg)
        return (seed, pitch, deform), rows, time.time() - t0, None
    except Exception as e:      # noqa: BLE001 - report which task failed, keep the rest going
        import traceback
        return (seed, pitch, deform), [], time.time() - t0, traceback.format_exc()


def run(seeds, steps, pitches, deforms, size, cache, out, jobs=1, resume=True, cfg=None, log=print):
    cfg = cfg or calib.Cfg()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    done_path = out + ".done"
    done = set()
    if resume and os.path.isfile(out) and os.path.isfile(done_path):
        with open(done_path) as fh:
            done = {tuple(l.split()) for l in fh if l.strip()}
    else:
        for p in (out, done_path):
            if os.path.exists(p):
                os.remove(p)
    new = not os.path.isfile(out)
    tasks = [(s, p, d, tuple(steps), size, cache, cfg) for s in seeds for p in pitches for d in deforms
             if (str(s), f"{float(p):g}", d) not in done]
    log(f"{len(tasks)} tasks ({len(done)} already done), {jobs} jobs")
    failed = []
    with open(out, "a", newline="") as fh, open(done_path, "a") as dfh:
        w = csv.DictWriter(fh, fieldnames=calib.COLUMNS)
        if new:
            w.writeheader()
        it = (map(_work, tasks) if jobs <= 1 else mp.Pool(jobs).imap_unordered(_work, tasks))
        for n, (key, rows, dt, err) in enumerate(it, 1):
            if err:
                failed.append((key, err))
                log(f"[{n}/{len(tasks)}] FAILED {key}:\n{err}")
                continue
            w.writerows(rows)
            fh.flush()
            dfh.write(f"{key[0]} {float(key[1]):g} {key[2]}\n")
            dfh.flush()
            log(f"[{n}/{len(tasks)}] seed {key[0]} pitch {key[1]:g} {key[2]}: {len(rows)} rows, {dt:.0f} s")
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(HERE, "results", "grid.csv"))
    ap.add_argument("--cache", default=os.path.join(HERE, "cache"), help="rendered volumes (.npz); safe to delete")
    ap.add_argument("--seeds", default="0-19")
    ap.add_argument("--steps", default="2,5,10,20", help="tifxyz grid step, voxels")
    ap.add_argument("--pitches", default="8,15,30,60", help="sheet pitch, voxels")
    ap.add_argument("--deforms", default=",".join(calib.DEFORMS))
    ap.add_argument("--size", type=int, default=192, help="cube edge, voxels")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 1)))
    ap.add_argument("--fresh", action="store_true", help="ignore and overwrite an existing CSV")
    ap.add_argument("--auditor-centre", choices=["estimated", "truth"], default="estimated")
    a = ap.parse_args(argv)
    cfg = calib.Cfg(auditor_centre=a.auditor_centre)
    failed = run(parse_list(a.seeds, int), parse_list(a.steps, float), parse_list(a.pitches, float), a.deforms.split(","),
                 a.size, a.cache, a.out, a.jobs, not a.fresh, cfg, log=lambda m: print(m, file=sys.stderr, flush=True))
    print(a.out)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
