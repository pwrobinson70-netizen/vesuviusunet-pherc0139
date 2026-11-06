---
name: verify-pr
description: Run the repository's release checks on the current branch before opening or reviewing a PR - frozen-file checksums, tests, forbidden private-scroll strings, changelog and docs presence - and print a pasteable report. Use before every PR and when asked to verify a branch.
---

# verify-pr

Run from the repository root on the branch under test. Use `bash scripts/verify_pr.sh`; it does the steps below and prints a report. If the script is missing, do the steps by hand in this order and report each with PASS/FAIL.

1. Branch and head: `git rev-parse --abbrev-ref HEAD` and `git rev-parse HEAD`. The branch must not be `main`.
2. Frozen files: `sha256sum -c SHA256SUMS.txt`. Every line must say OK. Any FAILED means a 30 October file was edited: stop, revert that file, report.
3. Forbidden strings: grep every tracked file for the strings in the local, git-ignored `.private_forbidden.txt` (or `VUN_FORBIDDEN`), see CLAUDE.md rule 1. No list = FAIL (fails closed). Any hit is a FAIL and must be removed before anything else. Never print the matched strings in a report.
4. Tests: `python -m pytest -q -p no:cacheprovider -n 4`. Record passed / failed / xfailed / xpassed. XPASS counts as FAIL unless the PR removes that marker on purpose and says so.
5. Changelog: `git diff origin/main -- CHANGELOG.md` must be non-empty for any user-visible change.
6. Docs: if a new `vun-*` entry point was added to `pyproject.toml`, `docs/TOOLS.md` must mention it.
7. Size: no single new file over 25 MB (`git diff --stat origin/main`); test data must be cropped, not whole volumes.
8. Secrets and private paths: grep the diff for `token`, `ghp_`, `AKIA`, `C:\Users`, `/home/` and report any hit.

Report format (paste into the PR body):

```
verify-pr  <branch> @ <sha>
checksums   PASS|FAIL
forbidden   PASS|FAIL (<n> hits)
tests       <passed> passed, <failed> failed, <xfailed> xfailed, <xpassed> xpassed -> PASS|FAIL
changelog   PASS|FAIL|n/a
docs        PASS|FAIL|n/a
size        PASS|FAIL (largest new file <size>)
secrets     PASS|FAIL
verdict     READY|NOT READY
```

Never fix a FAIL silently: say what failed, fix it in a separate commit, re-run, and show both outputs.
