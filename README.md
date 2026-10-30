# VesuviusUNET on PHerc0139: native 9.4 µm vs 2.4 µm renders (rounds C7–C11)

A small 3-D U-Net, trained in under two hours on four boxes of PHerc0139, learns the scroll's published ink map on the **2.399 µm / 78 keV render read at zarr level 2 (9.6 µm in-plane)** and transfers it to an unseen segment, **w045, at AUC 0.81**. The same recipe on the **native 9.362 µm / 113 keV render does not learn (AUC 0.59)**. Halving the pixel size to 4.8 µm gave no further gain. A check against the September 2026 public human labels stopped at our own pre-registered alignment gate, so no result here rests on human labels yet.

The full write-up is [WRITEUP.md](WRITEUP.md). Every pass rule was written into a pre-registration log, with a UTC time stamp, before its result existed. That log is published in [log/](log/).

This is Part 2 of our October 2026 Progress Prize submission. Part 1 (rounds C3–C5 on PHerc0172 and PHerc0800) is earlier work.

## Results

| Round | What changed | Pre-registered gate | Result | Verdict |
| --- | --- | --- | --- | --- |
| C7 | native 9.362 µm / 113 keV render, depth 16 | w045 AUC ≥ 0.70 at e240 | 0.588 | FAIL |
| C7S | C7 with labels shifted ±9 px | HELPS if mean gain ≥ +0.10 and ≥ 3/4 boxes gain ≥ 0.05 | 0.510 / 0.544 base / 0.560 | neither shift helps |
| C8 | 2.399 µm / 78 keV render, level 2, 32 layers, labels R = 4 | LEARNS if own-box mean ≥ 0.70 and ≥ 3/4 boxes ≥ 0.65; does not if mean < 0.62 | mean 0.728, 4/4 | LEARNS |
| C9 | C8 ensemble on unseen w045 | ≥ 0.70 transfers; < 0.62 does not | **0.8086** (title 0.830) | TRANSFERS |
| C10 | as C8 at level 1 (4.8 µm), R = 2 | BETTER if diff ≥ +0.05 and ≥ 3/4 boxes up ≥ 0.03; WORSE if ≤ −0.05 | 0.736 vs 0.728 | NO CLEAR DIFFERENCE |
| C11 | C9 maps vs public human labels | grid shift ≤ 2 px, else stop | best shift (8, 2) px | STOPPED, not scored |

All AUCs measure agreement with the team's 2 µm ink-prediction map (`new_canon`), not accuracy against human labels. See "What this shows and does not show" in the write-up for the seven caveats.

## Repository layout

| Path | Contents |
| --- | --- |
| `WRITEUP.md` | The submitted write-up |
| `vesuvius_unet/` | The model and training package: 3-D U-Net, dataset with C5 normalisation and augmentation, losses, metrics, run-hygiene contract |
| `scripts/` | The round runners, converter, maps/ensemble scorer and helpers, byte-identical to the versions the write-up cites |
| `log/` | The cleaned pre-registration log (notes 322–443) and its index |
| `SHA256SUMS.txt` | sha256 of every file in this repository |

No checkpoints or scan data are stored here. Checkpoint and archive hashes are listed in the write-up's Reproducibility section.

## Verifying the hashes

The write-up cites each script by the first 16 hex characters of its sha256. The files here are byte-identical, so they verify directly:

```bash
sha256sum -c SHA256SUMS.txt
```

`.gitattributes` turns off line-ending conversion so the hashes survive a clone on Windows.

Two provenance notes:

- `vesuvius_unet/dataset.py` is the C5-patched dataset used on the pod. It was developed as `dataset_c5_sonnet_24102026.py` and installed on the pod as `vesuvius_unet/dataset.py`. The C8 run log records `dataset.py 910335e3d79c88f8` and `train.py 02677d660cceb0a0`; both match these files.
- The pod ran `metrics.py` c81aa68bc9b8. This repo ships the pre-patch copy (a5bfa8b0d2df), which differs only by a warning printed when scikit-learn is missing (23 Sept patch); the AUC computation is identical.
- The script comments contain a working nickname, "Pedro". It refers to Peter Robinson. The scripts are published unchanged so their cited hashes still verify.

## Reproducing a round

The scripts were written for a RunPod GPU pod with a network volume mounted at `/workspace`:

```
/workspace/
  VesuviusUNET/vesuvius_unet/   <- this repo's vesuvius_unet/
  *.sh, *.py                    <- this repo's scripts/
```

Each round runner documents its own sub-commands in its header. For example, `scripts/c8_finescan_fable_27102026_rev1c.sh` runs in this order: `meta`, `fetch dry`, `fetch go`, `r1`, `stats`, `prep dry`, `prep go`, `go`. The runners download only the chunks they need from the public open-data bucket, write a summary and a sha256-named archive, then stop the pod under a hard time cap. They read `RUNPOD_POD_ID` and `RUNPOD_API_KEY` from the pod's environment for the self-stop; no keys are stored here.

Install PyTorch for your CUDA version, then `pip install -r requirements.txt`. The C8 four-model run took about 1.2 hours on one NVIDIA L4.

## Data

All data is public, from the [Vesuvius Challenge open-data bucket](https://scrollprize.org/data_browser): PHerc0139 segments w042, w043, w044, w045, w047 and the title. The 2.399 µm volume is `20260102150214`. Labels are the bucket's `new_canon` ink maps. Scan data is licensed CC BY-NC 4.0 by the Vesuvius Challenge and is not redistributed here.

## Related work

This work builds on community results, credited in full in the write-up: `scrollprize/ink_9um`, `tifxyz_label_transfer` in ScrollPrize/villa, Hyojun Kwon's ink experiments (khj1222/vesuvius-challenge), `domenicor046/ink9um-dense`, ProbeGuide, and Angelotti et al., arXiv 2606.29085.

## Licence and credit

Code: MIT, © 2026 Peter Robinson. See [LICENSE](LICENSE).

AI-assisted: two Claude agents cross-reviewed every plan, script and result in writing. The work was human-directed by Peter Robinson.
