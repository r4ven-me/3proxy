#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")/.."
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
exec python3 -m unittest discover -s tests -v "$@"
