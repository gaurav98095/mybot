#!/usr/bin/env bash
set -euo pipefail

find . -type d -name "__pycache__" -print -exec rm -rf {} +
find . -type d -name "*.egg-info" -print -exec rm -rf {} +
find . -type f -name "*.pyc"      -print -delete

echo "done"
