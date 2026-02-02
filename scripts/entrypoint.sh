#!/bin/bash

set -x

rm -rf .venv
uv venv .venv
source .venv/bin/activate
uv sync --no-install-package ccm
uv pip install --editable $CCM_DIR

exec "$@"
