# Ground-truth patch scoring (default thresholds)

AI-assisted (Claude Code and Claude), human-directed. Data: PHerc. Paris 4 (Scroll 1), CC BY-NC 4.0.

Patches: 40. Every patch is a human-verified correct trace, so PASS is correct.
Extra auditor arguments: `(none)`.

| mode | PASS | FAIL | NOT JUDGED | ERROR | false-alarm rate FAIL/N (Wilson 95%) |
|---|---|---|---|---|---|
| default | 0 | 7 | 33 | 0 | 7/40 = 17.5% (8.7-31.9%) |
| global-pitch(--pitch-vox) | 0 | 9 | 31 | 0 | 9/40 = 22.5% (12.3-37.5%) |
| alt-default | 0 | 0 | 40 | 0 | 0/40 = 0.0% (0.0-8.8%) |
| alt-global-pitch | 0 | 7 | 33 | 0 | 7/40 = 17.5% (8.7-31.9%) |

## Reasons not PASS: default

| verdict | reason (numbers masked) | patches |
|---|---|---|
| NOT JUDGED | winding_jumps: run of # points / # deg is too short | 33 |
| FAIL | switch_finder: vertical switch at z=# col # row # (inward, step # pitch, confidence #) | 2 |
| FAIL | switch_finder: horizontal switch at z=# col # row # (inward, step # pitch, confidence #) | 2 |
| FAIL | winding_jumps: radius jumps # pitch at z=#, col #, angle # deg | 2 |
| FAIL | switch_finder: vertical switch at z=# col # row # (outward, step # pitch, confidence #) | 1 |

## Reasons not PASS: global-pitch(--pitch-vox)

| verdict | reason (numbers masked) | patches |
|---|---|---|
| NOT JUDGED | winding_jumps: run of # points / # deg is too short | 31 |
| FAIL | switch_finder: vertical switch at z=# col # row # (outward, step # pitch, confidence #) | 3 |
| FAIL | switch_finder: horizontal switch at z=# col # row # (inward, step # pitch, confidence #) | 3 |
| FAIL | switch_finder: vertical switch at z=# col # row # (inward, step # pitch, confidence #) | 2 |
| FAIL | winding_jumps: radius jumps # pitch at z=#, col #, angle # deg | 2 |
| FAIL | switch_finder: horizontal switch at z=# col # row # (outward, step # pitch, confidence #) | 1 |

## Reasons not PASS: alt-default

| verdict | reason (numbers masked) | patches |
|---|---|---|
| NOT JUDGED | pitch_confidence: only #% of the cut line has a trusted local pitch (confidence >= # over  | 40 |
| NOT JUDGED | pitch_confidence: need #%): a PASS would mean nothing here | 40 |
| NOT JUDGED | winding_jumps: run of # points / # deg is too short | 39 |
| NOT JUDGED | switch_finder: only # of # heights could be followed (tracked fraction >= #) | 9 |
| NOT JUDGED | switch_finder: tracked # | 9 |
| NOT JUDGED | winding_jumps: local pitch confidence too low everywhere on this line | 3 |

## Reasons not PASS: alt-global-pitch

| verdict | reason (numbers masked) | patches |
|---|---|---|
| NOT JUDGED | winding_jumps: run of # points / # deg is too short | 33 |
| FAIL | switch_finder: vertical switch at z=# col # row # (inward, step # pitch, confidence #) | 2 |
| FAIL | switch_finder: horizontal switch at z=# col # row # (inward, step # pitch, confidence #) | 2 |
| FAIL | winding_jumps: radius jumps # pitch at z=#, col #, angle # deg | 2 |
| FAIL | switch_finder: vertical switch at z=# col # row # (outward, step # pitch, confidence #) | 1 |

## Per patch (default mode)

| patch | verdict | pitch h1/h2/h3 | wn jumps | audit switches | ssf switches all/flagged |
|---|---|---|---|---|---|
| band-seed10017187-20260729-201 | NOT JUDGED | 11.000/12.000/18.500 | 0 | 0 | 1/0 |
| band-seed1028766-20260730-0013 | NOT JUDGED | 13.250/10.750/10.500 | 0 | 0 | 1/0 |
| band-seed10512761-20260729-185 | NOT JUDGED | 14.000/11.250/15.875 | 0 | 0 | 0/0 |
| band-seed10615701-20260729-175 | NOT JUDGED | 12.000/13.000/12.500 | 0 | 0 | 0/0 |
| band-seed10838035-20260729-202 | NOT JUDGED | 13.500/11.000/10.500 | 0 | 0 | 5/0 |
| band-seed10941716-20260729-173 | NOT JUDGED | 17.125/16.000/11.000 | 0 | 0 | 1/0 |
| band-seed11419335-20260729-164 | NOT JUDGED | 12.750/15.000/15.625 | 0 | 0 | 0/0 |
| band-seed11609951-20260729-182 | NOT JUDGED | 12.250/13.000/13.500 | 0 | 0 | 1/0 |
| band-seed1180640-20260729-2221 | NOT JUDGED | 15.500/13.875/14.750 | 0 | 0 | 1/0 |
| band-seed12103508-20260729-172 | NOT JUDGED | 11.500/10.500/11.000 | 0 | 0 | 0/0 |
| band-seed12303143-20260729-210 | NOT JUDGED | 13.250/12.500/11.250 | 0 | 0 | 0/0 |
| band-seed12704141-20260729-224 | NOT JUDGED | 28.500/23.000/14.750 | 0 | 0 | 0/0 |
| band-seed13037713-20260729-203 | NOT JUDGED | 16.500/13.500/13.500 | 0 | 0 | 3/0 |
| band-seed13218168-20260729-171 | FAIL | 9.750/10.000/11.375 | 0 | 1 | 2/1 |
| band-seed13364832-20260730-003 | NOT JUDGED | 13.250/13.875/14.500 | 0 | 0 | 0/0 |
| band-seed13533491-20260729-192 | NOT JUDGED | 15.375/13.250/14.750 | 0 | 0 | 0/0 |
| band-seed137103-20260730-00204 | NOT JUDGED | 13.250/14.500/20.750 | 0 | 0 | 0/0 |
| band-seed1465356-20260729-1603 | FAIL | 10.875/12.500/12.250 | 0 | 1 | 2/1 |
| band-seed14835206-20260730-004 | NOT JUDGED | 12.000/12.250/10.500 | 0 | 0 | 2/0 |
| band-seed15003009-20260729-170 | NOT JUDGED | 11.125/13.125/14.250 | 0 | 0 | 0/0 |
| band-seed15125391-20260729-232 | NOT JUDGED | 10.500/10.750/11.500 | 0 | 0 | 0/0 |
| band-seed15372108-20260729-164 | NOT JUDGED | 9.875/13.750/13.000 | 0 | 0 | 3/0 |
| band-seed15606684-20260729-231 | NOT JUDGED | 11.250/12.000/12.250 | 0 | 0 | 3/0 |
| band-seed15735188-20260729-184 | NOT JUDGED | 12.250/13.875/11.750 | 0 | 0 | 0/0 |
| band-seed15994369-20260729-225 | NOT JUDGED | 12.000/12.250/10.500 | 0 | 0 | 2/0 |
| band-seed1610817-20260730-0033 | FAIL | 10.000/13.000/13.000 | 0 | 1 | 2/1 |
| band-seed16244965-20260729-170 | NOT JUDGED | 12.000/12.250/14.000 | 0 | 0 | 1/0 |
| band-seed16658040-20260729-213 | NOT JUDGED | 10.000/12.500/11.500 | 0 | 0 | 0/0 |
| band-seed17109446-20260729-173 | FAIL | 12.000/13.500/12.875 | 0 | 1 | 1/1 |
| band-seed17221198-20260729-221 | NOT JUDGED | 15.250/16.125/17.750 | 0 | 0 | 0/0 |
| band-seed17356252-20260729-210 | NOT JUDGED | 11.250/12.875/12.750 | 0 | 0 | 0/0 |
| band-seed17485725-20260729-182 | NOT JUDGED | 11.500/11.500/13.750 | 0 | 0 | 1/0 |
| band-seed17615994-20260729-232 | NOT JUDGED | 13.250/13.625/12.000 | 0 | 0 | 0/0 |
| band-seed17901491-20260729-174 | NOT JUDGED | 11.250/13.625/13.750 | 0 | 0 | 0/0 |
| band-seed18235570-20260729-173 | FAIL | 14.000/17.375/12.500 | 3 | 0 | 3/0 |
| band-seed18384563-20260729-185 | NOT JUDGED | 12.625/13.500/13.500 | 0 | 0 | 0/0 |
| band-seed18550190-20260729-194 | FAIL | 11.500/13.500/11.000 | 3 | 0 | 0/0 |
| band-seed18725348-20260729-204 | NOT JUDGED | 9.375/10.750/11.250 | 0 | 0 | 0/0 |
| band-seed18913366-20260729-212 | NOT JUDGED | 12.000/11.000/12.000 | 0 | 0 | 0/0 |
| band-seed1910856-20260729-1941 | FAIL | 14.125/14.500/12.500 | 0 | 1 | 3/1 |

## surface_agreement (from a checkout of origin/tool/surface-agreement)

ON-PREDICTED-SHEET: 1314/1949 judged points = 67.4% over 40 patches (height verdicts PASS 38 / FAIL 62 / NOT JUDGED 20 of 120; our CT-peak judge and the prediction agree on 965/1949 compared points).
