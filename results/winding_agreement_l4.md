# Winding numbers: our sweep vs the annotated absolute numbers (level 4)

AI-assisted (Claude Code and Claude), human-directed.

Overrides: none (winding_sweep defaults).

Annotated points: 59 at 5 heights; matched to a ray crossing within 0.5 pitch: 54.

(a) raw agreement (sweep index == absolute number): 0/54.

| z level-4 | points | matched | most common offset (abs - sweep) | points at that offset | median abs error after removing it (windings) | max abs error |
|---|---|---|---|---|---|---|
| 2115 | 8 | 7 | +28 | 2 | 2.0 | 4 |
| 2668 | 1 | 1 | +33 | 1 | 0.0 | 0 |
| 3567 | 1 | 1 | +29 | 1 | 0.0 | 0 |
| 3924 | 48 | 44 | +20 | 3 | 9.5 | 27 |
| 3994 | 1 | 1 | +9 | 1 | 0.0 | 0 |

(c) agreement after removing the per-height constant: 8/54 = 14.8%; typical error (median |error|) 6.0 windings, mean 9.35, worst 27.
Single-point heights agree trivially with their own constant, so the figure is driven by the 48- and 8-point rays; see the CSV.

z=2115: sweep crossings per annotated winding (fit slope) 0.14; annotated radial spacing 7.8 level-4 px per winding; sweep's measured local pitch (median) 21.4 px.

z=3924: sweep crossings per annotated winding (fit slope) 0.27; annotated radial spacing 5.7 level-4 px per winding; sweep's measured local pitch (median) 23.0 px.

(b) implied constant per point (absolute - sweep): min 9, max 47, distribution {9: 1, 14: 1, 15: 1, 16: 2, 17: 2, 20: 3, 21: 2, 22: 2, 23: 3, 25: 1, 26: 2, 27: 1, 28: 4, 29: 3, 30: 4, 31: 1, 32: 2, 33: 2, 34: 2, 35: 1, 36: 1, 37: 1, 38: 1, 39: 1, 40: 1, 41: 1, 42: 1, 44: 1, 45: 2, 46: 3, 47: 1}.

Unmatched points: 5 (no crossing within match tolerance).
