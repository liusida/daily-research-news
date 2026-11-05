#!/usr/bin/env bash
# Daily job (run by cron on the server): build the newest digest, publish the page, save data to git.
# Safe to run many times: it does nothing if the newest arXiv batch already has a digest.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
WEB_ROOT="${WEB_ROOT:-/var/www/daily.liusida.com}"
exec 9>.daily.lock; flock -n 9 || { echo "another run is in progress"; exit 0; }

echo "== $(date -u '+%F %T UTC')"
git pull --ff-only -q
D=$(uv run collect.py --print-latest)
if [ -f "digests/$D.md" ]; then echo "digest for $D already exists, nothing to do"; exit 0; fi

uv run collect.py --date "$D"
uv run filter.py --backend jev --date "$D"
uv run summarize.py --date "$D"
uv run build_site.py
mkdir -p "$WEB_ROOT" && cp site/index.html "$WEB_ROOT/index.html"

git add raw digests
git commit -qm "Digest $D"
git push -q
echo "published $D"
