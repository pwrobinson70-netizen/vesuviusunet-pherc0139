# Single-threshold sweep on the 40 verified patches (default mode, one flag changed at a time)

AI-assisted (Claude Code and Claude), human-directed.

| flag | value | PASS | FAIL | NOT JUDGED | FAIL rate (Wilson 95%) |
|---|---|---|---|---|---|
| (default) | default | 0 | 7 | 33 | 17.5% (8.7-31.9%) |
| min-switch-confidence | 0.4 | 0 | 4 | 36 | 10.0% (4.0-23.1%) |
| min-switch-confidence | 0.5 | 0 | 2 | 38 | 5.0% (1.4-16.5%) |
| min-switch-confidence | 0.6 | 0 | 2 | 38 | 5.0% (1.4-16.5%) |
| wn-min-span-deg | 3 | 1 | 31 | 8 | 77.5% (62.5-87.7%) |
| wn-min-span-deg | 5 | 1 | 29 | 10 | 72.5% (57.2-83.9%) |
| wn-min-span-deg | 10 | 0 | 20 | 20 | 50.0% (35.2-64.8%) |
| wn-min-span-deg | 30 | 0 | 7 | 33 | 17.5% (8.7-31.9%) |
| wn-jump-pitch | 1.0 | 0 | 7 | 33 | 17.5% (8.7-31.9%) |
| wn-jump-pitch | 1.5 | 1 | 6 | 33 | 15.0% (7.1-29.1%) |
| wn-jump-pitch | 2.0 | 1 | 6 | 33 | 15.0% (7.1-29.1%) |
| wn-jump-pitch | 3.0 | 2 | 5 | 33 | 12.5% (5.5-26.1%) |
| wn-min-points | 10 | 1 | 7 | 32 | 17.5% (8.7-31.9%) |
| wn-min-points | 8 | 1 | 7 | 32 | 17.5% (8.7-31.9%) |
| ssf-k-points | 8 | 0 | 6 | 34 | 15.0% (7.1-29.1%) |
