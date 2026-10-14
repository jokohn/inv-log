#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  printf 'Run the setup steps in README.md first.\n'
  exit 1
fi
exec .venv/bin/python -m app
