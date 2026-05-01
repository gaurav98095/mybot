#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Colours
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${YELLOW}mybot test runner${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Resolve Python ────────────────────────────────────────────────────────────
# Prefer: explicit $PYTHON env var → active venv → conda base → system python3
if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif command -v python3 &>/dev/null && python3 -c "import pytest" &>/dev/null; then
  PY="python3"
elif [[ -x "${CONDA_PREFIX:-}/bin/python3" ]]; then
  PY="${CONDA_PREFIX}/bin/python3"
elif [[ -x "$HOME/miniconda3/bin/python3" ]]; then
  PY="$HOME/miniconda3/bin/python3"
elif [[ -x "$HOME/anaconda3/bin/python3" ]]; then
  PY="$HOME/anaconda3/bin/python3"
else
  PY="python3"
fi

echo "Python: $("$PY" --version 2>&1)  ($PY)"

# ── Dependency check ──────────────────────────────────────────────────────────
if ! "$PY" -c "import pytest" 2>/dev/null; then
  echo -e "\n${YELLOW}pytest not found — installing test deps...${NC}"
  "$PY" -m pip install pytest pytest-asyncio -q
fi

# ── Run pytest ────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Running tests...${NC}\n"

ARGS=(
  "$ROOT/tests/"
  --tb=short
  -v
  "$@"   # forward any extra args: -k "test_bus", --pdb, -x, etc.
)

if "$PY" -m pytest "${ARGS[@]}"; then
  echo -e "\n${GREEN}✓ All tests passed${NC}"
else
  echo -e "\n${RED}✗ Tests failed${NC}"
  exit 1
fi
