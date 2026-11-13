#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-.venv/bin/python}
PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m unittest discover -s tests -v
