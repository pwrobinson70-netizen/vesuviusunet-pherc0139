# Winding numbers: our sweep vs the annotated absolute numbers (level 4)

AI-assisted (Claude Code and Claude), human-directed.

Overrides: ['pitch_vox=6', 'ray_sigma=0.5', 'ray_prominence=0.1'].

Annotated points: 59 at 5 heights; matched to a ray crossing within 0.5 pitch: 57.

(a) raw agreement (sweep index == absolute number): 0/57.

| z level-4 | points | matched | most common offset (abs - sweep) | points at that offset | median abs error after removing it (windings) | max abs error |
|---|---|---|---|---|---|---|
| 2115 | 8 | 8 | +13 | 3 | 1.0 | 3 |
| 2668 | 1 | 1 | +22 | 1 | 0.0 | 0 |
| 3567 | 1 | 1 | +18 | 1 | 0.0 | 0 |
| 3924 | 48 | 46 | +16 | 6 | 3.5 | 11 |
| 3994 | 1 | 1 | +8 | 1 | 0.0 | 0 |

(c) agreement after removing the per-height constant: 12/57 = 21.1%; typical error (median |error|) 2.0 windings, mean 3.40, worst 11.
Single-point heights agree trivially with their own constant, so the figure is driven by the 48- and 8-point rays; see the CSV.

z=2115: sweep crossings per annotated winding (fit slope) 0.71; annotated radial spacing 7.9 level-4 px per winding; sweep's measured local pitch (median) 9.4 px.

z=3924: sweep crossings per annotated winding (fit slope) 0.65; annotated radial spacing 5.7 level-4 px per winding; sweep's measured local pitch (median) 8.7 px.

(b) implied constant per point (absolute - sweep): min 8, max 27, distribution {8: 1, 9: 2, 10: 6, 11: 4, 12: 3, 13: 4, 14: 6, 15: 4, 16: 6, 17: 2, 18: 5, 19: 1, 20: 1, 21: 2, 22: 2, 23: 1, 24: 2, 25: 2, 26: 1, 27: 2}.

Unmatched points: 2 (no crossing within match tolerance).
