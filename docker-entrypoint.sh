#!/bin/sh
# Run flalac as PUID:PGID (MeTube/linuxserver style) when the container starts as root.
# Rootless Podman with UserNS=keep-id already starts as your own user; then nothing changes.
set -eu

umask "${UMASK:-022}"

if [ "$(id -u)" = "0" ]; then
    PUID="${PUID:-1000}"
    PGID="${PGID:-1000}"
    mkdir -p "${CONFIG_DIR:-/config}"
    if [ "${CHOWN_CONFIG:-true}" = "true" ]; then
        chown -R "$PUID:$PGID" "${CONFIG_DIR:-/config}"
    fi
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi

exec "$@"
