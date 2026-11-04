# Ground-truth patch scoring (default thresholds)

AI-assisted (Claude Code and Claude), human-directed. Data: PHerc. Paris 4 (Scroll 1), CC BY-NC 4.0.

Patches: 40. Every patch is a human-verified correct trace, so PASS is correct.
Extra auditor arguments: `(none)`.

| mode | PASS | FAIL | NOT JUDGED | ERROR | false-alarm rate FAIL/N (Wilson 95%) |
|---|---|---|---|---|---|
| default | 0 | 10 | 30 | 0 | 10/40 = 25.0% (14.2-40.2%) |
| global-pitch(--pitch-vox) | 0 | 36 | 4 | 0 | 36/40 = 90.0% (76.9-96.0%) |

## Reasons not PASS: default

| verdict | reason (numbers masked) | patches |
|---|---|---|
| NOT JUDGED | pitch_confidence: only #% of the cut line has a trusted local pitch (confidence >= # over  | 30 |
| NOT JUDGED | pitch_confidence: need #%): a PASS would mean nothing here | 30 |
| NOT JUDGED | winding_jumps: run of # points / # deg is too short | 29 |
| FAIL | switch_finder: vertical switch at z=# col # row # (inward, step # pitch, confidence #) | 7 |
| FAIL | switch_finder: horizontal switch at z=# col # row # (inward, step # pitch, confidence #) | 2 |
| FAIL | switch_finder: vertical switch at z=# col # row # (outward, step # pitch, confidence #) | 2 |
| NOT JUDGED | winding_jumps: local pitch confidence too low everywhere on this line | 2 |
| NOT JUDGED | switch_finder: only # of # heights could be followed (tracked fraction >= #) | 1 |
| NOT JUDGED | switch_finder: tracked # | 1 |
| FAIL | winding_jumps: radius jumps # pitch at z=#, col #, angle # deg | 1 |

## Reasons not PASS: global-pitch(--pitch-vox)

| verdict | reason (numbers masked) | patches |
|---|---|---|
| FAIL | switch_finder: vertical switch at z=# col # row # (inward, step # pitch, confidence #) | 28 |
| FAIL | switch_finder: vertical switch at z=# col # row # (outward, step # pitch, confidence #) | 27 |
| FAIL | switch_finder: horizontal switch at z=# col # row # (outward, step # pitch, confidence #) | 8 |
| NOT JUDGED | winding_jumps: run of # points / # deg is too short | 4 |
| FAIL | switch_finder: horizontal switch at z=# col # row # (inward, step # pitch, confidence #) | 3 |
| FAIL | winding_jumps: radius jumps # pitch at z=#, col #, angle # deg | 2 |
| NOT JUDGED | switch_finder: only # of # heights could be followed (tracked fraction >= #) | 1 |
| NOT JUDGED | switch_finder: tracked # | 1 |

## Per patch (default mode)

| patch | verdict | pitch h1/h2/h3 | wn jumps | audit switches | ssf switches all/flagged |
|---|---|---|---|---|---|
| band-seed10017187-20260729-201 | NOT JUDGED | 8.750/12.000/12.250 | 0 | 0 | 4/1 |
| band-seed1028766-20260730-0013 | NOT JUDGED | 9.750/9.000/9.000 | 0 | 0 | 17/4 |
| band-seed10512761-20260729-185 | NOT JUDGED | 10.500/9.000/12.250 | 0 | 0 | 12/4 |
| band-seed10615701-20260729-175 | NOT JUDGED | 9.500/9.250/9.000 | 0 | 0 | 19/5 |
| band-seed10838035-20260729-202 | FAIL | 11.750/9.250/8.500 | 0 | 1 | 25/8 |
| band-seed10941716-20260729-173 | NOT JUDGED | 8.750/8.500/8.250 | 0 | 0 | 17/5 |
| band-seed11419335-20260729-164 | NOT JUDGED | 8.750/9.000/7.500 | 0 | 0 | 5/1 |
| band-seed11609951-20260729-182 | NOT JUDGED | 10.000/11.000/10.750 | 0 | 0 | 14/4 |
| band-seed1180640-20260729-2221 | NOT JUDGED | 9.250/9.000/8.500 | 0 | 0 | 25/7 |
| band-seed12103508-20260729-172 | NOT JUDGED | 9.250/10.750/8.500 | 0 | 0 | 7/2 |
| band-seed12303143-20260729-210 | NOT JUDGED | 8.500/9.000/8.500 | 0 | 0 | 22/6 |
| band-seed12704141-20260729-224 | NOT JUDGED | 21.750/15.750/13.000 | 0 | 0 | 1/0 |
| band-seed13037713-20260729-203 | NOT JUDGED | 9.000/9.250/8.000 | 0 | 0 | 19/1 |
| band-seed13218168-20260729-171 | NOT JUDGED | 8.000/7.500/7.250 | 0 | 0 | 8/3 |
| band-seed13364832-20260730-003 | FAIL | 8.000/8.500/8.500 | 0 | 2 | 23/8 |
| band-seed13533491-20260729-192 | NOT JUDGED | 9.250/8.250/8.500 | 0 | 0 | 2/0 |
| band-seed137103-20260730-00204 | NOT JUDGED | 11.500/10.250/13.750 | 0 | 0 | 5/2 |
| band-seed1465356-20260729-1603 | FAIL | 8.250/9.250/9.000 | 0 | 1 | 25/13 |
| band-seed14835206-20260730-004 | NOT JUDGED | 9.000/8.000/8.500 | 0 | 0 | 8/1 |
| band-seed15003009-20260729-170 | NOT JUDGED | 7.750/8.750/8.000 | 0 | 0 | 3/2 |
| band-seed15125391-20260729-232 | NOT JUDGED | 7.500/7.500/8.500 | 0 | 0 | 6/3 |
| band-seed15372108-20260729-164 | FAIL | 8.000/8.000/8.000 | 0 | 1 | 26/11 |
| band-seed15606684-20260729-231 | NOT JUDGED | 9.250/9.500/9.250 | 0 | 0 | 43/15 |
| band-seed15735188-20260729-184 | NOT JUDGED | 11.500/12.000/11.000 | 0 | 0 | 6/3 |
| band-seed15994369-20260729-225 | NOT JUDGED | 7.500/7.750/8.000 | 0 | 0 | 36/6 |
| band-seed1610817-20260730-0033 | NOT JUDGED | 8.000/9.500/8.500 | 0 | 0 | 13/4 |
| band-seed16244965-20260729-170 | NOT JUDGED | 10.000/9.500/8.500 | 0 | 0 | 8/4 |
| band-seed16658040-20260729-213 | FAIL | 8.750/7.500/7.000 | 0 | 2 | 9/4 |
| band-seed17109446-20260729-173 | NOT JUDGED | 12.000/10.000/9.500 | 0 | 0 | 13/5 |
| band-seed17221198-20260729-221 | NOT JUDGED | 12.250/10.750/14.000 | 0 | 0 | 5/1 |
| band-seed17356252-20260729-210 | NOT JUDGED | 7.500/7.375/7.250 | 0 | 0 | 12/1 |
| band-seed17485725-20260729-182 | FAIL | 8.500/10.000/10.500 | 0 | 2 | 14/6 |
| band-seed17615994-20260729-232 | NOT JUDGED | 10.250/9.500/8.750 | 0 | 0 | 5/2 |
| band-seed17901491-20260729-174 | NOT JUDGED | 10.500/11.500/11.000 | 0 | 0 | 13/2 |
| band-seed18235570-20260729-173 | NOT JUDGED | 8.500/10.250/8.750 | 0 | 0 | 21/6 |
| band-seed18384563-20260729-185 | NOT JUDGED | 7.500/7.000/8.000 | 0 | 0 | 18/6 |
| band-seed18550190-20260729-194 | FAIL | 8.500/9.000/9.250 | 1 | 1 | 25/10 |
| band-seed18725348-20260729-204 | FAIL | 8.000/9.000/8.125 | 0 | 1 | 15/4 |
| band-seed18913366-20260729-212 | FAIL | 7.500/8.750/8.000 | 0 | 1 | 15/8 |
| band-seed1910856-20260729-1941 | FAIL | 9.000/10.000/11.000 | 0 | 1 | 17/8 |

surface_agreement was not run (no `--surface-root`).
