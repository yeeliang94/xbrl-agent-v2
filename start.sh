#!/usr/bin/env bash
# Start XBRL Agent v2 on http://localhost:8100 (or PORT from .env), on the Mac.
# Sets up what is missing first: the Python environment, its packages and the
# browser app. A step whose inputs have not changed is skipped
# (scripts/startup_cache.py), so later starts are quick.
set -e
cd "$(dirname "$0")"
export PYTHONUTF8=1

python_ok() {   # true when "$1" is Python 3.12 or newer
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1
}

# ---- The Python environment: made when missing, remade when broken or too old ----
if [ -e venv ] && ! { [ -x venv/bin/python ] && python_ok venv/bin/python; }; then
    echo "The Python environment is broken or older than 3.12; making a new one."
    rm -rf venv
fi
if [ ! -x venv/bin/python ]; then
    PYTHON_BIN=""
    for candidate in python3.13 python3.12 python3 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
        if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then
            PYTHON_BIN=$(command -v "$candidate")
            break
        fi
    done
    if [ -z "$PYTHON_BIN" ]; then
        echo "Python 3.12 or newer is needed. Install it with: brew install python@3.12"
        exit 1
    fi
    echo "Making the Python environment with $PYTHON_BIN..."
    "$PYTHON_BIN" -m venv venv
fi

if venv/bin/python scripts/startup_cache.py check pip; then
    echo "Python packages unchanged; skipping the install."
else
    echo "Installing Python packages..."
    venv/bin/python -m pip install -q -r requirements.txt   # requirements.txt applies constraints.txt
    venv/bin/python scripts/startup_cache.py mark pip
fi

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Made .env from .env.example. Add your keys to it."
fi

# ---- Node.js: often installed but not on PATH (nvm, Homebrew) ----
if ! command -v node >/dev/null 2>&1; then
    for dir in $(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V -r) /opt/homebrew/bin /usr/local/bin; do
        if [ -x "$dir/node" ]; then
            export PATH="$dir:$PATH"
            break
        fi
    done
fi

# ---- The browser app ----
if command -v node >/dev/null 2>&1; then
    echo "Node.js $(node --version)"
    if venv/bin/python scripts/startup_cache.py check npm; then
        echo "Browser app packages unchanged; skipping the install."
    else
        echo "Installing the browser app's packages..."
        (cd web && npm ci)
        venv/bin/python scripts/startup_cache.py mark npm
    fi
    if venv/bin/python scripts/startup_cache.py check build; then
        echo "Browser app unchanged; skipping the build."
    else
        echo "Building the browser app..."
        (cd web && npm run build)
        venv/bin/python scripts/startup_cache.py mark build
    fi
elif [ -f web/dist/index.html ]; then
    echo "WARNING: Node.js not found. Using the browser app built earlier, which may be out of date."
else
    echo "WARNING: Node.js not found, so the browser app cannot be built. Install it from nodejs.org."
fi

echo "Starting the server..."
exec venv/bin/python -m app.main
