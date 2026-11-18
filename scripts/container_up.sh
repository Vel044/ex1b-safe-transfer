#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
.venv/bin/python scripts/prepare_container.py
mkdir -p runtime/ssh/hostkeys
if [ ! -s runtime/ssh/authorized_keys ]; then
  public_key=${1:-"$HOME/.ssh/id_rsa.pub"}
  if [ ! -f "$public_key" ]; then
    printf '%s\n' "找不到 SSH 公钥，请传入公钥路径：sh scripts/container_up.sh /path/to/key.pub" >&2
    exit 1
  fi
  cp "$public_key" runtime/ssh/authorized_keys
fi
chmod 600 runtime/ssh/authorized_keys
docker compose build
# A disposable root initializer changes ownership only on this project's mounts.
docker run --rm --user 0 --entrypoint sh \
  -v "$PWD/runtime/container-data:/data" -v "$PWD/runtime/server-certs:/certs" \
  -v "$PWD/runtime/container-bootstrap:/bootstrap:ro" \
  "$(docker compose config --images)" \
  -c 'python /app/init.py; chown -R 10001:10001 /data /certs; chmod 700 /data/private; chmod 750 /certs; chmod 640 /certs/server.key'
docker compose up -d --wait
