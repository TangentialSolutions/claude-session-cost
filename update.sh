#!/usr/bin/env bash
# Update claude-session-cost in place, no clone needed:
#   curl -fsSL https://raw.githubusercontent.com/TangentialSolutions/claude-session-cost/main/update.sh | bash
#   curl -fsSL .../update.sh | bash -s -- --ref v0.4.0
# Downloads claude_cost.py to a temp file, verifies it (non-empty, py_compile, --version),
# backs up the current copy (keeps the last 3) and replaces it atomically.
# Never touches settings.json, the pricing override, or ~/.claude/claude-cost/.
# Env: CLAUDE_COST_HOME (install dir, default ~/.claude), CLAUDE_COST_UPDATE_URL (full URL override).
# Portable: bash 3.2+, BSD/GNU coreutils, curl, python3.
set -euo pipefail

REF="main"
HOME_DIR="${CLAUDE_COST_HOME:-$HOME/.claude}"
KEEP=3

usage() { echo "usage: update.sh [--ref <branch|tag|sha>] [--home <dir>]"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) [ $# -ge 2 ] || { usage >&2; exit 2; }; REF="$2"; shift 2 ;;
    --ref=*) REF="${1#--ref=}"; shift ;;
    --home) [ $# -ge 2 ] || { usage >&2; exit 2; }; HOME_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "update.sh: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

URL="${CLAUDE_COST_UPDATE_URL:-https://raw.githubusercontent.com/TangentialSolutions/claude-session-cost/${REF}/claude_cost.py}"
TARGET="$HOME_DIR/claude_cost.py"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "update.sh: python3 not found" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "update.sh: curl not found" >&2; exit 1; }

mkdir -p "$HOME_DIR"
TMP="$(mktemp "$HOME_DIR/.claude_cost.XXXXXX")"   # same filesystem -> atomic mv
CACHE="$(mktemp -d "${TMPDIR:-/tmp}/claude_cost_pyc.XXXXXX")"
trap 'rm -f "$TMP"; rm -rf "$CACHE"' EXIT

file_version() {
  if [ -f "$1" ]; then
    v="$(sed -n 's/^__version__ *= *["'\'']\([^"'\'']*\)["'\''].*/\1/p' "$1" | head -n 1)"
    echo "${v:-unknown}"
  else
    echo "none"
  fi
}

if ! curl -fsSL --retry 2 -o "$TMP" "$URL"; then
  echo "update.sh: download failed: $URL" >&2; exit 1
fi
[ -s "$TMP" ] || { echo "update.sh: empty download from $URL" >&2; exit 1; }
# py_compile writes bytecode; keep it out of ~/.claude
if ! PYTHONPYCACHEPREFIX="$CACHE" "$PY" -m py_compile "$TMP" 2>/dev/null; then
  echo "update.sh: downloaded file does not compile" >&2; exit 1
fi
if ! NEW_OUT="$("$PY" -B "$TMP" --version 2>/dev/null)" || [ -z "$NEW_OUT" ]; then
  echo "update.sh: downloaded file failed --version" >&2; exit 1
fi
NEW_V="${NEW_OUT##* }"
OLD_V="$(file_version "$TARGET")"

if [ -f "$TARGET" ] && cmp -s "$TMP" "$TARGET"; then
  echo "claude-cost $OLD_V: already up to date"
  exit 0
fi

if [ -f "$TARGET" ]; then
  BAK="$TARGET.bak-$(date +%Y%m%d-%H%M%S)"
  [ -e "$BAK" ] && BAK="$BAK-$$"
  cp -p "$TARGET" "$BAK"
  echo "backup: $BAK"
  # keep the newest $KEEP backups (names sort chronologically)
  BAKS=("$TARGET".bak-*)          # glob expansion is sorted, oldest first
  N=${#BAKS[@]}
  I=0
  while [ "$I" -lt $((N - KEEP)) ]; do
    [ -e "${BAKS[$I]}" ] && rm -f "${BAKS[$I]}"
    I=$((I + 1))
  done
fi

chmod 755 "$TMP"
mv -f "$TMP" "$TARGET"
echo "claude-cost updated: $OLD_V -> $NEW_V ($TARGET)"
