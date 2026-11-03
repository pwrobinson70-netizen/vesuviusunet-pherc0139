#!/usr/bin/env bash
# verify_pr.sh - release checks for vesuviusunet-pherc0139. Run from the repo root. Exit 1 on any FAIL.
set -u
ok=1
branch=$(git rev-parse --abbrev-ref HEAD); sha=$(git rev-parse --short HEAD)
echo "verify-pr  $branch @ $sha"
[ "$branch" = "main" ] && { echo "branch      FAIL (on main)"; ok=0; }

if sha256sum -c SHA256SUMS.txt --quiet >/dev/null 2>&1; then echo "checksums   PASS"; else echo "checksums   FAIL"; sha256sum -c SHA256SUMS.txt 2>/dev/null | grep -v ': OK$'; ok=0; fi

pat='PHerc0175A|PHerc 0175A|0175A|PHerc0483A|PHerc 0483A|0483A|20250521115057|20250521140913|S1 seed|S2 seed'
hits=$(grep -rIlE "$pat" --exclude-dir=.git --exclude=verify_pr.sh --exclude=SKILL.md --exclude=CLAUDE.md . | wc -l)
if [ "$hits" -eq 0 ]; then echo "forbidden   PASS"; else echo "forbidden   FAIL ($hits files)"; grep -rIlE "$pat" --exclude-dir=.git --exclude=verify_pr.sh --exclude=SKILL.md --exclude=CLAUDE.md .; ok=0; fi

out=$(python -m pytest -q -p no:cacheprovider -n 4 2>&1 | tail -n 3)
p=$(echo "$out" | grep -oE '[0-9]+ passed' | head -1 | cut -d' ' -f1); f=$(echo "$out" | grep -oE '[0-9]+ failed' | head -1 | cut -d' ' -f1)
xf=$(echo "$out" | grep -oE '[0-9]+ xfailed' | head -1 | cut -d' ' -f1); xp=$(echo "$out" | grep -oE '[0-9]+ xpassed' | head -1 | cut -d' ' -f1)
p=${p:-0}; f=${f:-0}; xf=${xf:-0}; xp=${xp:-0}
if [ "$f" -eq 0 ] && [ "$xp" -eq 0 ] && [ "$p" -gt 0 ]; then t=PASS; else t=FAIL; ok=0; fi
echo "tests       $p passed, $f failed, $xf xfailed, $xp xpassed -> $t"

git fetch -q origin main
if git diff --quiet origin/main -- CHANGELOG.md; then echo "changelog   n/a (unchanged; required for user-visible changes)"; else echo "changelog   PASS"; fi

if git diff origin/main -- pyproject.toml | grep -qE '^\+.*vun-'; then
  missing=0; for ep in $(git diff origin/main -- pyproject.toml | grep -oE '^\+\s*"?(vun-[a-z0-9_-]+)' | grep -oE 'vun-[a-z0-9_-]+' | sort -u); do grep -q "$ep" docs/TOOLS.md || { echo "docs        FAIL ($ep not in docs/TOOLS.md)"; missing=1; ok=0; }; done
  [ "$missing" -eq 0 ] && echo "docs        PASS"
else echo "docs        n/a"; fi

big=$(git diff --name-only --diff-filter=A origin/main | xargs -r -I{} stat -c '%s {}' {} 2>/dev/null | sort -n | tail -1)
sz=$(echo "$big" | cut -d' ' -f1); sz=${sz:-0}
if [ "$sz" -gt 26214400 ]; then echo "size        FAIL (largest new file $sz bytes: $(echo "$big" | cut -d' ' -f2-))"; ok=0; else echo "size        PASS (largest new file ${sz} bytes)"; fi

if git diff origin/main | grep -E '^\+' | grep -qE 'ghp_|AKIA|C:\\Users|/home/[a-z]'; then echo "secrets     FAIL"; git diff origin/main | grep -E '^\+' | grep -nE 'ghp_|AKIA|C:\\Users|/home/[a-z]' | head; ok=0; else echo "secrets     PASS"; fi

[ "$ok" -eq 1 ] && echo "verdict     READY" || echo "verdict     NOT READY"
exit $(( ok == 1 ? 0 : 1 ))
