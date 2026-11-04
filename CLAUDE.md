# CLAUDE.md - standing rules for every Claude session on vesuviusunet-pherc0139

Read this before doing anything. These rules override the brief you were given if they conflict; say so and stop rather than break one.

## What this repository is
Public CPU tools for checking traced papyrus surfaces (tifxyz meshes) from the Vesuvius Challenge: sheet spacing, sheet switches, umbilicus, trace auditing, tracing, repair, calibration, phantom scrolls, benchmarks, real-data runs, winding sweeps, patch merging, ink inference. Entry points are `vun-*` (see `pyproject.toml`); docs are in `docs/` (`TOOLS.md`, `FORMATS.md`, `OPERATING_RANGE.md`, `BENCHMARK_CI.md`, `REALDATA_STATUS.md`). Licence MIT. Test data under `testdata/` is public Scroll 1 (PHerc. Paris 4) material, CC BY-NC 4.0.

## Hard rules
1. PRIVACY. Never write, commit, log or print the names, scan ids or any data of the private First Letters targets. Forbidden strings: `PHerc0175A`, `PHerc 0175A`, `0175A`, `PHerc0483A`, `PHerc 0483A`, `0483A`, `20250521115057`, `20250521140913`, `S1 seed`, `S2 seed`. If a brief mentions them, stop and report. Only PHerc. Paris 4 (Scroll 1) and PHerc. 0139 data may appear here.
2. FROZEN FILES. Do not edit any file listed in `SHA256SUMS.txt` (the 30 October release). Add new files or new modules instead. `sha256sum -c SHA256SUMS.txt` must pass on every branch.
3. NO IRREVERSIBLE PRESSES. Open PRs as drafts. Do not merge, close, force-push to main, delete branches, change settings, or post outside this repository. Pedro merges.
4. NO SECRETS. Never ask for, store or print tokens, keys or passwords. If a push is refused with "not in this session's authorized repository set", say so and stop; the repository has to be attached to the session by Pedro.
5. ONE BRANCH PER SESSION, named `tool/<name>`, `fix/<name>`, `testdata/<name>` or `docs/<name>`, from `origin/main`. Never work on main.
6. KEEP WORK PUBLIC-SAFE. No private paths, no usernames, no machine names, no screenshots of Pedro's desktop.

7. NO COMMAND MAY WAIT FOR INPUT OR RUN WITHOUT A LIMIT. Prefix every git command with `--no-pager` (`git --no-pager diff`, `git --no-pager log`); export `GIT_PAGER=cat PAGER=cat GIT_TERMINAL_PROMPT=0` at the start of the session; wrap every long command in `timeout` (`timeout 900 python -m pytest -q -p no:cacheprovider -n 4`); never run anything interactive (editors, `git rebase -i`, `less`, `more`, confirmation prompts). If a command has run for more than 10 minutes with no output, kill it and continue with a smaller step. (Two overnight sessions once sat 7.5 hours on a `git diff` that opened a pager.)

## How to work
- Python: `python -m pip install -e ".[test]" pytest-xdist` then `python -m pytest -q -p no:cacheprovider -n 4`. All tests must pass before a PR; new behaviour needs new tests.
- Strict xfails in `tests/test_realdata.py` pin known real-data failures. A fix that makes one pass must remove that marker in the same PR and say so in the PR body. An XPASS is a failure, by design.
- `tests/test_benchmark_ci.py::test_small_run_writes_csv` has a 90 s wall-clock limit and can fail on a slow runner. Report it; do not loosen it unless the brief says to.
- Windows users run these tools: text files CRLF-safe, paths through `os.path`/`pathlib`, no shell-only tricks in the CLI.
- Never write repo files with Windows PowerShell `Set-Content` or `Out-File`: they add a byte-order mark and CRLF, and Python's packaging rejects a `pyproject.toml` that starts with one. Write files from Python with `encoding="utf-8", newline="\n"`.
- Merging main into a branch: additive conflicts (CHANGELOG.md, docs/TOOLS.md, pyproject.toml, vun_tools/cli.py, tool READMEs) keep both sides, then remove any entry point or package listed twice and check `pyproject.toml` still parses (`python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"`). Re-scored result files and their pinned tests take the newer side and are re-run, never hand-merged.
- Changelog: add a line to `CHANGELOG.md` under Unreleased for every user-visible change. Docs: a new tool gets a section in `docs/TOOLS.md` and its format in `docs/FORMATS.md`.
- Numbers in a PR body must come from a file in the PR (CSV, JSON, md table). Label anything else "illustrative". Phantom results are phantom results; say which phantom and seed.
- Before opening the PR run `.claude/skills/verify-pr` (or `bash scripts/verify_pr.sh`) and paste its output into the PR body.
- If main has moved and GitHub reports a conflict, merge `origin/main` into your branch, resolve by keeping both sides for `CHANGELOG.md`, `docs/TOOLS.md`, `pyproject.toml`, `.gitignore`, `vun_tools/cli.py`, re-run tests, push.

## When you report
Start with the branch name and head sha. Then: what changed, test counts (passed / xfailed / failed), the verify-pr output, and anything you could not do. Plain English, no claims beyond the files. End with the line: `AI-assisted (Claude Code and Claude), human-directed.`
