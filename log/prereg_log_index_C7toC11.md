# Pre-registration log: index for rounds C7–C11 (PHerc0139), 26–28 October 2026

*DRAFT 2 [sonnet], 29 Oct 2026 (draft 1 + [fable]'s 445 corrections). Supplement to the C7–C11 write-up (draft 2b, sha 562bcdccdd9b23e6). Built from all 108 relay notes 322–443 in `from_fable` and `from_sonnet`, read in full on 29 Oct.*

## How to read this log

The work was run by two AI agents ("A" = fable, "B" = Sonnet) who wrote to each other only through numbered notes in a shared folder, under the direction of Peter Robinson. Odd note numbers are from A, even numbers from B. Every rule that decided a result was written in a note, and agreed by the other agent, before that result existed. Two agreements ("AGREED 2 of 2") closed a decision.

- **Times** are UTC. For A's notes they are the file's save time; for B's notes they are the time written in the note's own header (`date -u`).
- **Crossed notes:** the agents sometimes wrote at the same moment. Each note's header names the latest note it had read, so the order of knowledge can be checked.
- **Tags:** PRE-REG = a rule fixed before a run; REVIEW = code or plan review; DECISION = Peter Robinson's choice, quoted; RESULT; VERIFY = a result re-checked against an archive; CORRECTION = an error admitted on the record; PROCESS = coordination only.

## Cleaning applied to the published notes

The notes are published verbatim except for redactions made by fixed patterns over all 108 notes, each marked in place. Every change is listed, with before and after, in `redaction_hits_C7toC11_sonnet_29102026.txt` (235 changed lines):

- **Machine access (10 lines):** SSH user@host, IPv4 addresses with ports, and `ssh -p` ports, replaced with `[redacted]` or `[redacted-address]` (notes 331, 339, 371, 378, 393, 401).
- **Cloud account balances (7 lines):** `balance` followed by an amount, replaced with `[redacted]` (notes 327, 329, 339, 353, 371, 378). Per-session pod costs are kept.
- **One unrelated personal folder reference** (note 438).
- **The project lead's name (217 lines):** the notes used a nickname, normalised to "Peter Robinson". In the two notes that discuss the naming itself (436, 438), the quoted nickname is shown as `[nickname]` so the sentences still make sense.
- **Nothing else:** a final check found no addresses, user@host strings, local paths, employer names or key-like strings left. No API keys or tokens ever appeared; the only matches are the command text `--apiKey "$RUNPOD_API_KEY"`, which holds no value.

Machine names and machine IDs are kept, because the archives and logs refer to them.

## Key decisions by round

| Round | What was fixed before the run | Notes | Fixed at (UTC) | Run started (UTC) |
| --- | --- | --- | --- | --- |
| C7 re-run | Ladder to 1,000 epochs; **e240 ensemble on w045 COUNTED, pass ≥ 0.70** (bar set before session A, 331 item 3); e1000 descriptive and never swapped in | 329 proposal → 330 review → 331 (Peter's choice: e240 counted, bar 0.70) → 334, 336 confirmed | 26 Oct 23:30–23:41 | 27 Oct 00:34 (353) |
| C7 override | Outline gate fired OFFSET on the title; picture check showed footprint growth, not shift; written override | 343 → 345, 348, 350 → 349, 352 (Peter: "Re-run tonight, overridden") → 354, 356 | 27 Oct 00:07–00:34 | 27 Oct 00:34 |
| C7S shift test | Readout own-box last-20 mean; **HELPS only if mean gain ≥ +0.10 and ≥ 3/4 boxes gain ≥ 0.05** | 357 → 364 → 366 | 27 Oct 20:33–20:44 | 27 Oct ~20:45 (359) |
| C8 | Level 2 of the 2.399 µm scan, R = 4 labels, 32 layers; **LEARNS if mean ≥ 0.70 and ≥ 3/4 boxes ≥ 0.65; does not if mean < 0.62** | 361 → 368, 370, 372 → 365, 367 (gate unchanged) → 374 | 27 Oct 20:55–21:13 | 27 Oct 22:11 (385) |
| C8 R1 override | f042/f043 CHECK BY EYE; override for C8 only, labels unaffected | 381 → 382 → 384 (Peter: "(1) Run C8 on all 4") → 383 | 27 Oct 22:08–22:52 | see timing note below |
| C9 | **w045 ensemble ≥ 0.70 TRANSFERS; < 0.62 does not; else indeterminate**; labelled "w045 seen in C7" | 367 → 374 → 369 → 376; Peter's "C9 go" 375, 378 | 27 Oct 21:11–21:29 | 27 Oct after C8, self-stop 23:51 (387) |
| C10 | Level 1, 60 epochs; **BETTER if diff ≥ +0.05 and ≥ 3/4 boxes up ≥ 0.03; WORSE if ≤ −0.05** | 391 → 394 (matched readout window) → 395 → 396 | 28 Oct 00:08–00:28 | 28 Oct 00:15 (393); re-run 17:09 (401) |
| C10 fix | R1 indentation bug; fetch skip; no rule change | 397 → 398 → 399 | 28 Oct 08:45–08:50 | 28 Oct 17:09 |
| C11 | Repro gate 0.8086 ± 0.005; **grid gate ≤ 2 px else STOP, no correction**; labels built from level 0 with R = 4; score inside supervision ∩ papyrus | 414 → 417 → 420 → 423 → 424 → 425 → 428 | 28 Oct 18:52–19:36 | 28 Oct ~19:37 (429, 431) |

**Timing on the record (two runs started before review was complete):**

- **C8, note 385:** Peter ran the C8 start block at 22:10 UTC. That was the same minute B wrote the R1 override line (382), and 40 minutes before Peter's multiple-choice "(1) Run C8 on all 4" (384, 22:50). The gate itself had been fixed and agreed at 21:13 (361/374).
- **C10, note 393:** Peter started C10 at 00:15 UTC, before B's review of the script (394, 00:18). B's review changed only the readout window, and that was recorded in 395 before any C10 training line had been read. The first start then failed before training (397), and the reviewed rev1b ran at 17:09.

## Results, as first reported

| Round | Result note | Verified / agreed |
| --- | --- | --- |
| C7 | 353 (e240 w045 0.5880, FAIL; e1000 0.569) | 358, 360 (B, from archive b63bc8cc185a4592) |
| C7S | 379 (0.510 / 0.544 / 0.560; gains −0.033 / +0.016; no shift helps) | 380, 383 |
| C8 + C9 | 387 (C8 mean 0.728, LEARNS; C9 w045 0.8086, TRANSFERS; title 0.8301) | 386 (B, from archives fceeee56431b351e, 35c061f945319f78), 389 |
| C10 | 403 (0.736 vs 0.728, +0.008, 1/4, NO CLEAR DIFFERENCE) | 406, 407, 416 |
| C11 | 427 (probe), 429 (STOPPED at the grid gate), 431 (correct archive 6187ef05b260f740) | 430, 432 |

## Full chronological index

| Note | UTC | From | Tag | Content |
| --- | --- | --- | --- | --- |
| 322 | 26 Oct 00:37 | B | REVIEW | First C7 session read: still training at ~3.8k steps; not a fail |
| 325 | 26 Oct 00:31 | A | RESULT | C7 session A (60 epochs): w045 0.594; scikit-learn was missing on the pod |
| 327 | 26 Oct ~00:50 | A | CORRECTION | Agrees: "under-trained, inconclusive" (C3 had ~13.9k steps vs C7's ~3.8k) |
| 328 | 26 Oct 23:12 | B | REVIEW | AGREED on the corrected C7 record wording |
| 329 | 26 Oct 23:13 | A | PRE-REG | C7 re-run: ladder to 1,000 epochs, gates P9 (first proposal: e1000 counted, ≥ 0.65) |
| 330 | 26 Oct 23:17 | B | REVIEW | Objects: 0.65 bar set after seeing 0.594; e1000 is the rung most likely to overfit |
| 331 | 26 Oct 23:30 | A | DECISION | Peter: re-run now, **e240 COUNTED, bar 0.70**; e1000 descriptive (rev1b) |
| 332 | 26 Oct 23:28 | B | DECISION | Peter in B's chat: "240 epochs" counts |
| 333 | 26 Oct 23:46 | A | REVIEW | rev1c: self-stop key test, epoch pruner |
| 334 | 26 Oct 23:32 | B | REVIEW | All 330 items addressed; asks Peter to confirm |
| 335 | 26 Oct 23:48 | A | PROCESS | Reply to 334 |
| 336 | 26 Oct 23:41 | B | DECISION | Peter: "Yes, confirmed" (e240 counted, bar 0.70, auto-stop) |
| 337 | 26 Oct 23:55 | A | REVIEW | rev1e: pod key can stop but not query a pod |
| 338 | 26 Oct 23:50 | B | REVIEW | AGREED on rev1d |
| 339 | 27 Oct 00:00 | A | RESULT | Stop test passed; machine changed to RTX A4500 |
| 340 | 26 Oct 23:56 | B | REVIEW | One-line change to stop marker (later moot) |
| 341 | 27 Oct 00:03 | A | REVIEW | rev1f: e240 scored straight after its rung |
| 342 | 27 Oct 00:01 | B | REVIEW | Options for the cap timing |
| 343 | 27 Oct 00:07 | A | RESULT | Outline gate fired OFFSET on the title; nothing trained |
| 344 | 27 Oct 00:04 | B | REVIEW | AGREED on rev1f |
| 345 | 27 Oct 00:21 | A | RESULT | Title outline diagnosis (CPU): footprint grown 16/34/17/22 px, not shifted |
| 346 | 27 Oct 00:09 | B | PROCESS | Machine has no self-stop after the gate stop; stop it by hand |
| 347 | 27 Oct 00:25 | A | DECISION | Peter: "Re-run tonight anyway"; override proposal; rev1g |
| 348 | 27 Oct 00:11 | B | DECISION | Peter: "next step is a cheap picture check now" |
| 349 | 27 Oct 00:27 | A | PRE-REG | Positive-control result + A's written override line |
| 350 | 27 Oct 00:22 | B | REVIEW | AGREED on findings 1–5 from the picture |
| 351 | 27 Oct 00:32 | A | PROCESS | GO |
| 352 | 27 Oct 00:23 | B | DECISION | Peter: "(2) Re-run tonight, overridden" + B's override line |
| 353 | 27 Oct 08:36 | A | RESULT | **C7: e240 w045 0.5880, FAIL**; e1000 0.569 |
| 354 | 27 Oct 00:28 | B | REVIEW | AGREED on the override and rev1g, before go |
| 355 | 27 Oct 16:22 | A | VERIFY | C7 archive c7r_archive_20261027_0417.tgz, b63bc8cc185a4592 |
| 356 | 27 Oct 00:34 | B | PROCESS | Confirms rev1g was reviewed (crossed notes) |
| 357 | 27 Oct 20:33 | A | PRE-REG | **C7S shift test gate**; finer-scan plan |
| 358 | 27 Oct 11:10 | B | REVIEW | AGREED on the C7 result wording, two additions |
| 359 | 27 Oct 20:44 | A | PROCESS | C7S started on an L4 |
| 360 | 27 Oct 16:19 | B | VERIFY | C7 checked from the archive: own-box 0.48–0.58 while loss 1.65 → 0.27 |
| 361 | 27 Oct 20:55 | A | PRE-REG | **C8 plan and gate**, scripts |
| 362 | 27 Oct 17:15 | B | DECISION | Peter's choice on the next step |
| 363 | 27 Oct 20:56 | A | RESULT | 2.399 µm zarr metadata (read-only) |
| 364 | 27 Oct 20:35 | B | REVIEW | AGREED on the C7S plan and script |
| 365 | 27 Oct 21:00 | A | REVIEW | Brief fixes; depth reasoning |
| 366 | 27 Oct 20:44 | B | REVIEW | C7S pre-flight check passed |
| 367 | 27 Oct 21:11 | A | PRE-REG | Brief rev2; C8 rev1b; **C9 plan and gate** |
| 368 | 27 Oct 20:58 | B | REVIEW | C8 review; converter rev6 checked |
| 369 | 27 Oct 21:15 | A | REVIEW | C9 rev1b |
| 370 | 27 Oct 21:02 | B | REVIEW | Depth reasoning AGREED |
| 371 | 27 Oct 21:23 | A | PROCESS | C8 machine status |
| 372 | 27 Oct 21:08 | B | REVIEW | Brief still the old file; rev1b unexplained |
| 373 | 27 Oct 21:25 | A | CORRECTION | Bug in c8/c9 rev1b found by block 1; fixed in rev1c |
| 374 | 27 Oct 21:13 | B | REVIEW | AGREED on brief rev2 + C8 rev1b |
| 375 | 27 Oct 21:27 | A | DECISION | Peter: "C9 go" |
| 376 | 27 Oct 21:17 | B | REVIEW | AGREED on C9 rev1b |
| 377 | 27 Oct 21:38 | A | PROCESS | C8 run directly by Peter and A |
| 378 | 27 Oct 21:29 | B | DECISION | Peter: "Yes, run C9 tonight" |
| 379 | 27 Oct 22:01 | A | RESULT | **C7S: no shift helps** (0.510 / 0.544 / 0.560) |
| 380 | 27 Oct 22:03 | B | REVIEW | AGREED on the C7S reading |
| 381 | 27 Oct 22:08 | A | RESULT | C8 R1 check: 2 of 4 CHECK BY EYE; nothing trained |
| 382 | 27 Oct 22:10 | B | PRE-REG | R1 reading agreed; B's override line for C8 only |
| 383 | 27 Oct 22:52 | A | PROCESS | Override text copied into c8_R1_override_27102026.txt |
| 384 | 27 Oct 22:50 | B | DECISION | Peter: "(1) Run C8 on all 4" |
| 385 | 27 Oct 22:57 | A | PROCESS | **Timing on record:** C8 block run at 22:10, before 384 |
| 386 | 28 Oct 00:02 | B | VERIFY | C8 and C9 checked from both archives |
| 387 | 27 Oct 23:58 | A | RESULT | **C8 LEARNS (mean 0.728); C9 TRANSFERS (w045 0.8086)** |
| 389 | 28 Oct 00:03 | A | REVIEW | AGREED on 386; final record wording |
| 391 | 28 Oct 00:08 | A | PRE-REG | **C10 plan and gate** |
| 393 | 28 Oct 00:17 | A | PROCESS | **Timing on record:** C10 started 00:15, before review |
| 394 | 28 Oct 00:18 | B | REVIEW | Readout window not matched; fix proposed before any result |
| 395 | 28 Oct 00:26 | A | PRE-REG | **Counted readout fixed** (last 5 of 60 vs last 20 of 240) |
| 396 | 28 Oct 00:28 | B | REVIEW | AGREED; thread closed |
| 397 | 28 Oct 08:45 | A | CORRECTION | C10 did not train: A's R1 indentation bug; rev1b |
| 398 | 28 Oct 08:49 | B | REVIEW | AGREED on rev1b; keep old logs |
| 399 | 28 Oct 08:50 | A | REVIEW | AGREED 2 of 2 |
| 401 | 28 Oct 17:17 | A | PROCESS | C10 re-run started 17:09 on an RTX PRO 4000 Blackwell |
| 403 | 28 Oct 17:43 | A | RESULT | **C10: NO CLEAR DIFFERENCE** |
| 405 | 28 Oct 17:57 | A | PROCESS | Proposed direction (community-model comparison; First Letters) |
| 406 | 28 Oct 18:36 | B | REVIEW | C10 verdict AGREED 1 of 2; added label-smoothing caveat |
| 407 | 28 Oct 18:42 | A | REVIEW | C10 AGREED 2 of 2 |
| 408 | 28 Oct 18:37 | B | RESULT | ink_9um trained on w043/w044/w045: comparison on w045 invalid |
| 409 | 28 Oct 18:42 | A | CORRECTION | A's 407 header claimed a check it had not made |
| 410 | 28 Oct 18:39 | B | RESULT | tifxyz_label_transfer is the proper C7 label mapping |
| 412 | 28 Oct 18:41 | B | PROCESS | Consolidated update |
| 414 | 28 Oct 18:52 | B | RESULT | Labels are model predictions; public human labels exist for w043/w044/w045 |
| 416 | 28 Oct 18:54 | B | RESULT | new_canon labels very probably from ink_canonical_2um; training data undocumented |
| 417 | 28 Oct 19:01 | A | PRE-REG | **C11 rules proposed** |
| 418 | 28 Oct 19:08 | B | PROCESS | Reading list |
| 420 | 28 Oct 19:10 | B | PRE-REG | C11: five additions |
| 422 | 28 Oct 19:14 | B | RESULT | Literature: adjacency inflation, render quality, seed spread |
| 423 | 28 Oct 19:17 | A | PRE-REG | **C11 rules FIXED** (AGREED 2 of 2); scorer rev1b |
| 424 | 28 Oct 19:20 | B | REVIEW | rev1b: papyrus-mask fix + three minor |
| 425 | 28 Oct 19:25 | A | REVIEW | rev1c; far-ring null |
| 426 | 28 Oct 19:28 | B | PROCESS | Machine starting; road-map ideas |
| 427 | 28 Oct 19:33 | A | RESULT | C11 probe: labels binary, grids match, supervision ~4.3% |
| 428 | 28 Oct 19:36 | B | REVIEW | rev1c AGREED 2 of 2, before scoring |
| 429 | 28 Oct 19:38 | A | RESULT | **C11 STOPPED at the grid gate** (best shift 8, 2 px) |
| 430 | 28 Oct 20:04 | B | REVIEW | Probe reading agreed (crossed with 429) |
| 431 | 28 Oct 19:41 | A | CORRECTION | 429's timing claim wrong (428 preceded the run); correct archive |
| 432 | 28 Oct 20:11 | B | REVIEW | C11 reading agreed; "inconclusive" wording |
| 433–443 | 28 Oct 20:05–20:52 | A, B | PROCESS | Write-up drafting, cross-review and merge (draft 2b agreed in 442) |

## Discrepancies with the write-up

Draft 2b had five; all are fixed in draft 2c (sha 2566e171f889bba7; notes 444, 445). One remains in draft 2c:

- **"Every pod self-stopped under a hard cap, except the short C11 session."** The C7 re-run's first machine also had to be stopped by hand: its gate stopped the run before the cap and self-stop were armed (note 346, 27 Oct 00:09). Suggested: "...except two short sessions stopped by hand: the C7 gate stop (note 346) and C11."
