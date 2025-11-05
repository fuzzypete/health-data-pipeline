#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   tools/cleanup_orphans.sh          # archive orphans into _archive/orphans_YYYYMMDD/
#   tools/cleanup_orphans.sh --delete # delete orphans instead of archiving
#   tools/cleanup_orphans.sh --ignore # also append guards to .gitignore
#
# Requires: ripgrep (rg) and Poetry in PATH.

MODE="archive"
ADD_IGNORE="no"
for arg in "$@"; do
  case "$arg" in
    --delete) MODE="delete" ;;
    --ignore) ADD_IGNORE="yes" ;;
    *) echo "Unknown arg: $arg"; exit 2 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

echo "==> Repo root: $ROOT"
echo "==> Mode: $MODE"
echo "==> Add .gitignore guards: $ADD_IGNORE"
echo

echo "==> Checking for root-level orphans"
mapfile -t ORPHANS < <(git ls-files ':/*ingest' ':/*validate' ':/common.py' ':/*common.py' 2>/dev/null | sed '/^$/d' || true)
if [[ ${#ORPHANS[@]} -eq 0 ]]; then
  echo "No orphan candidates found at repo root."
else
  printf "Found %d candidate(s):\n" "${#ORPHANS[@]}"
  for f in "${ORPHANS[@]}"; do echo "  - $f"; done
fi
echo

echo "==> Searching for imports referencing orphan names (code only)"
rg -n --hidden \
  --glob '!Data/**' --glob '!.venv/**' --glob '!venv/**' --glob '!.git/**' \
  -e '^(from|import)\s+(ingest|validate|common)\b' || true
echo

echo "==> Python import resolution (BEFORE) under Poetry"
poetry run python - <<'PY' || true
import importlib.util as U
names = ("ingest","validate","common","pipeline.common","pipeline.ingest.csv_delta")
for n in names:
    spec = U.find_spec(n)
    print(f"{n:28} -> {getattr(spec, 'origin', None)}")
PY
echo

STAMP="$(date +%Y%m%d)"
ARCHIVE_DIR="_archive/orphans_${STAMP}"
changed="no"

if [[ ${#ORPHANS[@]} -gt 0 ]]; then
  if [[ "$MODE" == "archive" ]]; then
    echo "==> Archiving orphans to: $ARCHIVE_DIR"
    mkdir -p "$ARCHIVE_DIR"
    for f in "${ORPHANS[@]}"; do
      git mv "$f" "$ARCHIVE_DIR"/ 2>/dev/null || mv "$f" "$ARCHIVE_DIR"/
      changed="yes"
    done
  else
    echo "==> Deleting orphans"
    for f in "${ORPHANS[@]}"; do
      git rm -r "$f" 2>/dev/null || rm -rf "$f"
      changed="yes"
    done
  fi
else
  echo "==> Nothing to archive/delete."
fi
echo

if [[ "$ADD_IGNORE" == "yes" ]]; then
  echo "==> Adding .gitignore guards"
  {
    echo ""
    echo "# Guard against reintroducing root-level modules"
    echo "/ingest/"
    echo "/validate/"
    echo "/common.py"
  } >> .gitignore
  git add .gitignore 2>/dev/null || true
  changed="yes"
  echo "Appended to .gitignore"
  echo
fi

if [[ "$changed" == "yes" ]]; then
  echo "==> Staging changes"
  git add -A || true
  if git diff --cached --quiet; then
    echo "No staged changes."
  else
    msg="chore: ${MODE} orphaned root modules (ingest/, validate/, common.py)"
    [[ "$ADD_IGNORE" == "yes" ]] && msg="$msg + add .gitignore guards"
    git commit -m "$msg" || true
  fi
else
  echo "==> No changes to commit."
fi
echo

echo "==> Python import resolution (AFTER) under Poetry"
poetry run python - <<'PY' || true
import importlib.util as U
names = ("ingest","validate","common","pipeline.common","pipeline.ingest.csv_delta")
for n in names:
    spec = U.find_spec(n)
    print(f"{n:28} -> {getattr(spec, 'origin', None)}")
PY

echo
echo "Done."
