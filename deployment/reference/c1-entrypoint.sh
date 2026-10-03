#!/bin/sh
# Copy mounted secrets to a private tmpfs owned by the c1 user, then drop root.
# Secret values are never printed. The root filesystem stays read-only.
set -eu
if [ "$(id -u)" = 0 ]; then
  install -d -m 0750 -o 10001 -g 10001 /run/c1
  install -d -m 0700 -o 10001 -g 10001 /run/c1/secrets
  if [ -d /run/secrets ]; then
    for file in /run/secrets/*; do
      [ -f "$file" ] || continue
      install -m 0400 -o 10001 -g 10001 "$file" "/run/c1/secrets/$(basename "$file")"
    done
  fi
  exec setpriv --reuid=10001 --regid=10001 --clear-groups --no-new-privs -- "$@"
fi
exec "$@"
