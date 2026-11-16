#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
.venv/bin/python -m pytest -q
swift test --package-path macos --build-system native -q
swift build --package-path macos --build-system native -q
macos/.build/debug/TransferProbe --certs runtime/certs --root "runtime/probe-$(date +%s)"
