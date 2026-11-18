#!/bin/sh
# Compatibility alias: the default container now includes SSH.
set -eu
cd "$(dirname "$0")/.."
sh scripts/container_up.sh "$@"
