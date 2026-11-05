#!/usr/bin/env bash
# Full daily pipeline: collect -> score with Jev -> write digest.
set -euo pipefail
cd "$(dirname "$0")"
uv run collect.py
uv run filter.py --backend jev
uv run summarize.py
uv run build_site.py
