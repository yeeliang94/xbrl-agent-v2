#!/usr/bin/env bash
# Build a source-only zip for a Veracode static scan, in veracode/.
# Run ./start.sh once first so the Python environment exists.
# Add --include-tests to include the tests. Rules: scripts/package.py.
set -e
cd "$(dirname "$0")/.."
export PYTHONUTF8=1
if [ ! -x venv/bin/python ]; then
    echo "ERROR: the Python environment is missing. Run ./start.sh once first."
    exit 1
fi
exec venv/bin/python scripts/package.py veracode "$@"
