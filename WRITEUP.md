# VesuviusUNET Progress Prize write-up, October 2026

*Part 2 of our October submission; Part 1 (rounds C3–C5 on PHerc0172 and PHerc0800) was earlier work. The pre-registration log cited as "log, note N" is published as a supplement.*

On PHerc0139, a small 3-D U-Net learned the team's ink map on the scan that map was made from (2.399 µm, read at zarr level 2 = 9.6 µm in-plane) and transferred it to an unseen segment, w045, at AUC 0.81. On the native 9.362 µm scan it did not learn (AUC 0.59). Halving the pixel size gave no further gain. An attempted check against the new public human labels stopped at our own pre-registered alignment gate, so no result here rests on human labels yet. The main result is a diagnosis, not a new ink model.

## Summary

This round continues the October draft (rounds C3–C5, PHerc0172 and PHerc0800) in the ~9 µm regime that most First Letters scrolls are scanned in. Every round had its gate written down and agreed by both agents before its result existed. Every number below comes from a named archive with a sha256, or, for C7S, from the run log (note 379).

- **C7 (negative):** models trained on the native 9.362 µm / 113 keV render memorised their boxes (train loss 0.26–0.28, own-box validation AUC 0.48–0.58) and scored 0.588 on held-out w045, below the 0.70 pass mark.
- **C7S (no evidence):** shifting the labels by ±9 px did not rescue C7 (0.510 / 0.544 / 0.560).
- **C8 (learns):** the same four boxes on the 2.399 µm / 78 keV render at level 2, with labels area-meaned at an exact R = 4, learned (own-box AUC 0.69–0.77, mean 0.728).
- **C9 (transfers):** the C8 four-model ensemble scored AUC 0.8086 on unseen w045 (members 0.72–0.82) and 0.83 on the title segment.
- **C10 (no clear difference):** the same experiment at 4.8 µm in-plane (level 1) gave 0.736 vs 0.728, below the pre-registered +0.05 bar.
- **C11 (stopped):** scoring C9 against the September 2026 public human labels stopped at the grid gate. The best alignment was (8, 2) px, on the edge of the search, so no human-label score is reported. This is inconclusive rather than evidence of misplacement.

All AUCs are agreement with the team's 2 µm ink-prediction map (new_canon), not accuracy against human labels. The caveats are listed under "What this shows and does not show".

## Results at a glance

| Round | Render and grid | Pre-registered gate | Result | Verdict |
| --- | --- | --- | --- | --- |
| C7 | native 9.362 µm / 113 keV, depth 16 | w045 AUC ≥ 0.70 at e240 (log, notes 331, 336) | 0.588 (e1000 descriptive 0.569; title 0.609 / 0.601) | FAIL |
| C7S | as C7, labels shifted (−9,−2) / (+9,+2) | HELPS if mean gain ≥ +0.10 and ≥ 3/4 boxes gain ≥ 0.05 (log, note 357) | own-box mean 0.510 / 0.544 base / 0.560 | neither shift helps |
| C8 | 2.399 µm / 78 keV, level 2 (9.596 µm xy), 32 layers [38,70), R = 4 | LEARNS if mean ≥ 0.70 and ≥ 3/4 boxes ≥ 0.65; does not if mean < 0.62 (log, note 361) | 0.688 / 0.750 / 0.708 / 0.765, mean 0.728 | LEARNS |
| C9 | C8 models on unseen w045 and the title | w045 ensemble ≥ 0.70 transfers; < 0.62 does not (log, note 367) | w045 0.8086 (members 0.719–0.817); title 0.830 (descriptive) | TRANSFERS |
| C10 | 2.399 µm level 1 (4.798 µm xy), R = 2, 60 epochs | better if diff ≥ +0.05 and ≥ 3/4 boxes up ≥ 0.03 (log, notes 391, 395) | 0.736 vs C8 0.728, diff +0.008, 1/4 boxes | NO CLEAR DIFFERENCE |
| C11 | C9 maps vs public human labels on w045 | repro 0.8086 ± 0.005; grid shift ≤ 2 px, else stop (log, notes 417, 420, 424) | repro 0.80864; best shift (8, 2) px | STOPPED, not scored |

## Data and setup

All data is public, from the Vesuvius Challenge open-data bucket for PHerc0139 (Philodemus, *On Gods*, Book 8).

| Item | Detail |
| --- | --- |
| Training segments | w042, w043, w044, w047: one fixed box each (2048² at 9.362 µm = 1998² at level 2) |
| Held-out | w045 (one box), plus the title segment |
| Scan A (C7) | 9.362 µm, 113 keV, 1.2 m propagation (per the volume name 9.362um-1.2m-113keV), native surface volume |
| Scan B (C8–C11) | 2.399 µm, 78 keV, 0.22 m propagation (volume 20260102150214); zarr level 2 = 9.596 µm in-plane, 2.399 µm in depth |
| Depth window | C7: 16 real layers; C8–C10: 32 of 109 layers, [38, 70), centred on the surface |
| Labels | the bucket's new_canon ink maps on Scan B, area-meaned onto each training grid, ink = block mean ≥ 128 |
| Model | small 3-D U-Net: 64 px patches, stride 64, 8 base channels, batch 8, BCE + Dice, lr 3e-4, no AMP, max aggregation over depth, seed 42; C5 intensity normalisation and augmentation |
| Readout | own-box validation AUC on held-out strips inside each box (descriptive); transfer AUC on w045 (counted) |

Every pass rule was written into the pre-registration log, with a UTC time stamp, before its result existed. Before training on any new scan we ran a same-surface check (R1): band-pass structure correlation between the new box and the old one, which must peak above 5× the median within a few pixels of zero shift.

## C7: the native 9.362 µm render does not learn

C7 trained on PHerc0139's native 9.362 µm / 113 keV render, the same recipe as the ~9 µm First Letters scrolls. It failed its gate, and the failure looks like memorisation rather than an absence of signal.

- **Setup:** four 2048² boxes on w042, w043, w044 and w047, placed by eye on letter lines; w045 held out. Depth 16 real layers, the C3 contract plus C5 normalisation and augmentation (L / S = 83.0 / 69.5), one seed.
- **Labels:** the team's 2.399 µm new_canon map, area-meaned onto the 9.362 grid (a non-integer scale of 3.90) and thresholded at 128.
- **Outline gate:** it fired OFFSET on the title, (17, −22). A synthetic control showed the map footprint is the scan footprint grown 16/34/17/22 px, not shifted. Overridden in writing with Peter Robinson's approval (log, notes 349 and 352).
- **Ladder:** e240 counted, e1000 descriptive, pass mark 0.70. e240 w045 0.588 (FAIL); e1000 0.569; title 0.609 / 0.601. An earlier, under-trained 60-epoch session had already scored w045 at 0.594 (log, notes 325–328), so the counted e240 number is a second look at w045; the 0.70 bar was set before that session.
- **Diagnosis:** training loss fell to 0.26–0.28 while own-box validation stayed at 0.48–0.58. Pod cost USD 1.16.

**C7S, a label-shift test:** if C7 failed because the labels sat a few pixels off, a shift should help. Same setup (depth 16) on an L4: own-box AUC means over the last 20 epochs were 0.544 for the C7 baseline, 0.510 with labels shifted (−9, −2) and 0.560 with (+9, +2); mean gains −0.033 and +0.016, and no box gained ≥ 0.05 either way (log, note 379; agreed in note 380), so neither shift met the registered gate (HELPS if mean gain ≥ +0.10 and ≥ 3/4 boxes gain ≥ 0.05; log, note 357). Two uniform shifts did not help, which is consistent with per-box rather than global offsets.

C7 likely failed on two counts, label mapping and scan quality, and we cannot yet separate them:

- **Label mapping:** our scale-only area-mean is an approximation. The villa tool `tifxyz_label_transfer` moves labels between renders by 3D surface geometry, and our per-box R1 offsets (w042 ~6 px, w043 ~14 px) are the kind its offset audit is meant to catch.
- **Render quality:** Kwon (GitHub khj1222, September 2026 progress prize) measured that the same sheet scores 0.053 F1 better rendered aligned than native, and that augmentations did not close the gap (khj1222/vesuvius-challenge).

## C8: the 2.399 µm render at level 2 learns

C8 kept C7's four boxes and training contract and changed the input to the render the labels were made on. All four models learned: own-box AUC 0.688 / 0.750 / 0.708 / 0.765, mean 0.728.

- **Input:** the 2.399 µm / 78 keV render's zarr level 2 (9.596 µm in-plane, 2.399 µm in z), 32 central layers [38, 70) of 109, depth 32, 240 epochs. Boxes are the C7 boxes mapped to level 2 (1998², origin-anchored).
- **Labels:** the same new_canon map, area-meaned with an exact integer R = 4 and thresholded at 128.
- **Normalisation:** C8's own L / S = 87.5 / 75.0 from its four boxes (C7 used 83.0 / 69.5 on its scan).
- **R1 same-surface check** (band-pass structure correlation, new render vs the C7 box): f044 and f047 SAME SURFACE; f042 (1, 6) and f043 (14, 3) CHECK BY EYE, overridden for C8 only and recorded (c8_R1_override_27102026.txt, log, note 382).
- **Run:** gate LEARNS = mean ≥ 0.70 and ≥ 3/4 boxes ≥ 0.65 (log, note 361). C8 met it: mean 0.728, 4/4 boxes ≥ 0.65, against 0.544 for C7 on the same boxes. About 1.2 h on one L4 (four models, ~18 min each, 22:11–23:23 UTC), self-stopping pod; archive c8_archive_20261027_2323.tgz (sha256 fceeee56431b351e…).

C8 changed several things at once relative to C7: render, beam energy, an exact label scale, and the depth window. It shows that the 2.399 render learns, not which change mattered.

## C9: the C8 models transfer to unseen w045

The C8 ensemble ranks the new_canon map on held-out w045 at AUC 0.8086, above the pre-registered 0.70 pass mark. That is the round's main result.

| Map on w045 (2.399 µm render, level 2) | AUC vs new_canon |
| --- | --- |
| member f042 | 0.7189 |
| member f043 | 0.7314 |
| member f044 | 0.7234 |
| member f047 | 0.8168 |
| **ensemble, pixel-wise mean of four** | **0.8086** |
| title segment, ensemble (descriptive) | 0.8301 |

- **Gate:** ≥ 0.70 transfers; < 0.62 does not; in between indeterminate (c9_night branch A).
- **R1 before scoring:** the fw45 box vs the C7 w045 box gave SAME SURFACE at (1, −1).
- **Run:** the overnight branch ran automatically after C8; the pod self-stopped at 23:51:48 UTC on 27 Oct. Archive c9_archive_20261027_2351.tgz (44,038,015 B, sha256 35c061f945319f78…).
- **Verification:** the second reviewer checked C8 and C9 against the archives (log, note 386), and the member and ensemble AUCs above were re-read from the C9 archive's score files on 28 Oct (mean member 0.7477; the ensemble beats every member but f047).
- **Already seen:** w045's labels were looked at in C7, though not with a model of this render.

Wording agreed by both reviewers: the C8 models trained on PHerc0139's 2.399 render "transfer to the unseen w045 box of the same scroll at AUC 0.81 (title 0.83)".

## C10: 4.8 µm in-plane is no better than 9.6 µm

C10 repeated C8 at level 1 (4.798 µm in-plane, labels R = 2) for 60 epochs, the same optimiser steps as C8's 240 because each box holds 4× the tiles. Result: NO CLEAR DIFFERENCE, 0.736 vs 0.728.

| Box | C10, last 5 of 60 epochs | C8, last 20 of 240 epochs | Difference |
| --- | --- | --- | --- |
| h042 | 0.679 | 0.688 | −0.009 |
| h043 | 0.740 | 0.750 | −0.010 |
| h044 | 0.797 | 0.708 | +0.088 |
| h047 | 0.727 | 0.765 | −0.038 |
| **mean** | **0.736** | **0.728** | **+0.008** |

- **Counted readout:** both windows are the last 8.3% of training, as pre-registered in the log, note 395 (c10_counted_fable_28102026.py, 8c9737859d4652e2), after the second reviewer showed that a last-20 vs last-20 comparison would be biased against C10 (note 394).
- **Gate:** better needs diff ≥ +0.05 and ≥ 3 of 4 boxes up ≥ 0.03; worse needs ≤ −0.05. Here: +0.008, 1 of 4.
- **Descriptive (post hoc):** C10 was not quicker. At 25% of steps it trailed C8 on all four boxes, and caught up by 50–75%.
- **Consequence:** the planned level-0 (2.4 µm in-plane) build was conditional on BETTER and was dropped.
- **Comparison caveat:** labels were R = 2 vs R = 4 area-means, so C10 tests resolution and label smoothing together.
- **Run:** the first start stopped at the R1 step on a script bug (an indented heredoc line in our R1 step), before any training. The re-run (rev1b, e8e15f5d60734940, reviewed before the run) was on an RTX PRO 4000 Blackwell (fp32, same seed), not an L4. R1 offsets matched C8's physically: h042 (2, 11) at 4.8 µm = (1, 5.5) at 9.6. Archive c10_archive_20261028_1740.tgz, sha256 4fbf39ef70577991…

This fits the community's choice of ~9.6 µm inputs for its cross-scroll ink model.

## C11: the human-label check stopped at the grid gate

We attempted an independent check against the September 2026 public human labels on w045. It stopped at the alignment gate and was not scored. The best alignment between the human labels and our grid was (8, 2) px at 9.6 µm, on the edge of the ±8 px search. This is inconclusive rather than evidence of misplacement: the gate correlated over the whole box, while the human labels cover only 4.3% of it.

- **Labels:** `20260126000000-w045_2026012619/ink-labels/2.399um-volume-20260102150214/20260918/{inklabels,supervision,validation}.zarr`, OME-Zarr 0.5, binary 0/255. Source entry 0139/w029_202601261946 (annotation name w029 = public w045), canvas_offset_yx (−19.8, −20.2) px at 2.399 µm.
- **Coverage:** supervision covers about 4.3% of the fw45 box. Validation is empty there.
- **Rules:** fixed before any score (log, notes 417, 420, 424, 425 and 428). Human labels are rebuilt from level 0 with our R = 4 rule (ink = block mean ≥ 128; supervision all-16). Then a repro gate, a grid gate (shift ≤ 2 px and r_best ≥ 3× a far-ring null), and pixel AUC inside supervision ∩ papyrus.
- **Repro gate:** PASSED. The archived C9 ensemble map rescored by the same scorer gave 0.80864 against 0.8086 recorded. sha16 of the four last.pt files were recorded.
- **Grid gate:** STOPPED. Best shift (dy, dx) = (8, 2), on the edge of the ±8 search; r_best 0.127, r(0,0) 0.108, far-ring median 0.027. Not shifted, not scored.
- **Archive:** c11_humanlabel_20261028_1937.tgz, sha256 6187ef05b260f740…; scorer c11_humanlabel_fable_28102026_rev1c.py, d3fa2a4001c37d55.

Two readings remain open. The gate correlated the whole box while human ink exists only inside the 4% supervised area, which dilutes the match. Or the two label sets are genuinely offset. A re-test that correlates inside supervision only, with a wider search used only to measure the offset, will be pre-registered after this submission.

## What this shows and does not show

It shows that a small U-Net, trained in under two hours on four boxes, learns PHerc0139's ink map on the 2.399 µm render at level 2 and carries it to an unseen segment at AUC 0.81. On the native 9.362 µm render it does not. The caveats, in the order both reviewers agreed:

1. **Pseudo-labels, not ground truth.** The labels are self-trained pseudo-labels from the team's fragment-pretrained, scroll-bootstrapped 2 µm model: recipe new_canon_autoresearch_recipe, very likely scrollprize/ink_canonical_2um. Its training data is undocumented and may include these segments. Every AUC here is agreement with that map, on the scan it was made from. The human-label check (C11) stopped at its gate, so no result here rests on human labels yet.
2. **w045 already looked at.** Its labels were seen in C7, though not with a model of this render.
3. **Several changes at once.** C7 → C8 changed render, energy, label scale (R = 4 exact) and depth window together. C10 changed resolution and label smoothing together.
4. **R1 override.** f042 and f043 were CHECK BY EYE and overridden for C8 only, in writing.
5. **One seed, one GPU type per round, fixed epochs.** For scale: ink_9um's two seeds differ by up to 0.22 F1 at the same step (Kwon), so differences of 0.01 mean nothing here.
6. **Own-box AUCs are likely inflated.** C8 and C10 validate on strips inside their training boxes, and Kwon measured that held-out pixels next to training pixels score higher. They are descriptive; the w045 number carries the claim.
7. **"Points to", not "proves".** C7's failure points to label transfer between renders and to native-render quality, both consistent with community measurements. It has not been isolated by a re-labelled C7.

Not comparable: the community model ink_9um was trained on public w043, w044 and w045 (annotation names w043 and w029). So no ours-vs-community score on w045 is reported.

## Related community work

Our findings agree with what the community already practises. We cite these as consistent prior practice, not as our discoveries.

- **ink_9um** (scrollprize/ink_9um, MIT) trains on the 2.399 µm volumes pooled to ~9.6 µm (level-2 XY, 4× z mean), the representation C8 found works. It warns of z-offset sensitivity.
- **tifxyz_label_transfer** (ScrollPrize/villa, volume-cartographer/scripts) moves labels between renders by 3D surface geometry, the correct method for C7's problem.
- **Kwon's ink experiments** (khj1222/vesuvius-challenge, September progress prize): the aligned-vs-native render gap, held-out adjacency inflation, seed spread, and weak cross-scroll transfer.
- **Dense pseudo-labels** (domenicor046/ink9um-dense) beat a matched manual-label control on three held-out regions, by +0.077, +0.100 and +0.026 balanced accuracy; the author notes that only the PHerc0814 gain clearly exceeds seed noise (model card; code at github.com/DomRusso2/ink9um-dense). That supports training on pseudo-labels, with the same seed-noise warning.
- **ProbeGuide** (September progress prize): with a decent teacher, filtering pseudo-labels by similarity removed real ink, while raising the teacher threshold worked as well. It was evaluated on the same 20260918 human-label release we used in C11.
- **arXiv 2606.29085**, "Complete virtual unwrapping and reading of a rolled Herculaneum papyrus" (Angelotti et al., June 2026): the fragment-pretrained, scroll-bootstrapped pseudo-label pipeline behind the new_canon maps, and the choice of 2.4 µm, 22 cm propagation and 78 keV as the optimal regime, which is our Scan B. This is the strongest external support for C8.

## Reproducibility

Every script ran from a hash-checked copy. Every gate was agreed by both agents before its result existed. Two runs started before review finished; both are disclosed in the log (notes 385, 393). Every pod self-stopped under a hard cap, except two short sessions stopped by hand: the C7 gate stop (log, note 346) and C11.

| Item | File | sha256 (first 16) |
| --- | --- | --- |
| Converter (zarr levels) | scroll_segment_convert_fable_27102026_rev6.py | 0a5c6b613a9a55a6 |
| C7 ladder runner | c7r_rerun_fable_26102026_rev1g.sh | c1dd73f44e4f031b |
| C7S shift test | c7s_shift_fable_27102026.sh | fd5a33efb44c831a |
| C8 runner | c8_finescan_fable_27102026_rev1c.sh | 209a04b544077d8c |
| C9 overnight branch | c9_night_fable_27102026_rev1c.sh | 147919b91854d8c1 |
| Maps and ensemble | c4_maps_fable_27102026_rev4c.py | 9727cb02d5cf1b80 |
| C10 runner | c10_l1_fable_28102026_rev1b.sh | e8e15f5d60734940 |
| C10 counted readout | c10_counted_fable_28102026.py | 8c9737859d4652e2 |
| C11 human-label scorer | c11_humanlabel_fable_28102026_rev1c.py | d3fa2a4001c37d55 |

Archives (sha256, first 16). C7: c7r_archive_20261027_0417.tgz (b63bc8cc185a4592). C7S has no separate archive; its results come from the run log (log, note 379) and are restated in the C9 summary file. Then:

- c8_archive_20261027_2323.tgz (174,793 B; fceeee56431b351e)
- c9_archive_20261027_2351.tgz (44,038,015 B; 35c061f945319f78)
- c10_archive_20261028_1740.tgz (249,268 B; 4fbf39ef70577991)
- c11_humanlabel_20261028_1937.tgz (9,229 B; 6187ef05b260f740)

The C8 checkpoints runs/c8_f04x_e240_27102026/last.pt are f042 ba3779e7a8b45606, f043 6c0183f67f57020f, f044 d47ae956c1b92f07 and f047 a1a83ecd68faaa7b.

Data: PHerc0139 segments w042, w043, w044, w045, w047 and the title, from the public open-data bucket. The 2.399 µm volume is 20260102150214; a newer 2.399 volume, 20260930100252, exists and was not used. Scans are CC BY-NC 4.0. Code is to be released under MIT with this submission.

AI-assisted (Claude: two agents with written cross-review of every plan, script and result), human-directed by Peter Robinson.

## Next steps

After this submission, each step gets its own pre-registered gate.

1. **C11 re-test:** correlate inside the supervised area only, and measure the offset with a wider search, for diagnosis only, never to shift and score.
2. **C7 re-labelled:** labels moved with tifxyz_label_transfer onto the 9.362 render, to pin C7's failure on label mapping or on render quality.
3. **Paired-render distillation:** train on native ~9 µm renders guided by a 2.4 µm teacher at mesh-matched points. Most First Letters scrolls have only ~9 µm scans, and PHerc0139 has both kinds. A novelty check against reader-v2 comes first. For scale: an automatic survey of 65 patches across 21 scrolls found no letters yet (Bullo27/first-letters-survey).

Also cheap and CPU-only: score the C8 and C10 own-box AUCs by distance from the nearest training pixel, to size how much adjacency inflates them.

## Sources

- [Vesuvius Challenge: Open Prizes](https://scrollprize.org/prizes)
- [Vesuvius Challenge: Winners](https://scrollprize.org/winners)
- [Data Browser](https://scrollprize.org/data_browser)
- [scrollprize/ink_9um](https://huggingface.co/scrollprize/ink_9um)
- [scrollprize/ink_canonical_2um](https://huggingface.co/scrollprize/ink_canonical_2um)
- [domenicor046/ink9um-dense](https://huggingface.co/domenicor046/ink9um-dense)
- [khj1222/vesuvius-challenge](https://github.com/khj1222/vesuvius-challenge)
- [Bullo27/first-letters-survey](https://github.com/Bullo27/first-letters-survey)
- arXiv 2606.29085, Complete virtual unwrapping and reading of a rolled Herculaneum papyrus (Angelotti et al., 27 Jun 2026; huggingface.co/papers/2606.29085)
