#!/bin/sh
set -eu
mkdir -p /run/sshd /home/transfer/.ssh /ssh-hostkeys
chmod 700 /home/transfer/.ssh /ssh-hostkeys
cp /ssh-authorized-keys /home/transfer/.ssh/authorized_keys
chown -R transfer:transfer /home/transfer/.ssh
chmod 600 /home/transfer/.ssh/authorized_keys
if [ ! -f /ssh-hostkeys/ssh_host_ed25519_key ]; then
  ssh-keygen -q -t ed25519 -N '' -f /ssh-hostkeys/ssh_host_ed25519_key
fi
/usr/sbin/sshd -D -e &
ssh_pid=$!
runuser -u transfer -- ex1b server --config /app/server.json &
server_pid=$!
trap 'kill "$ssh_pid" "$server_pid" 2>/dev/null || true; wait; exit' TERM INT
# Stop the container if either service exits, so health cannot hide a failed SSH daemon.
while kill -0 "$ssh_pid" 2>/dev/null && kill -0 "$server_pid" 2>/dev/null; do
  sleep 1
done
kill "$ssh_pid" "$server_pid" 2>/dev/null || true
wait || true
exit 1
