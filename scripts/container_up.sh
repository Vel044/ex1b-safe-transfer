#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
.venv/bin/python scripts/prepare_container.py
docker compose build
# A disposable root initializer changes ownership only on this project's mounts.
docker run --rm --user 0 --entrypoint sh \
  -v "$PWD/runtime/container-data:/data" -v "$PWD/runtime/server-certs:/certs" \
  "$(docker compose images -q server)" \
  -c 'chown -R 10001:10001 /data /certs; chmod 700 /data/private; chmod 750 /certs; chmod 640 /certs/server.key'
docker compose up -d
