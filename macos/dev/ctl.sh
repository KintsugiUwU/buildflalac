#!/bin/bash
# Sends one command to a development build of Flalac (DEV=1 ./build.sh) started with
# FLALAC_DEV_OUT=<folder>, and waits until it has run. Example: dev/ctl.sh sync
# Commands: see run(_:_:) in dev/DevControl.swift.
set -euo pipefail
: "${FLALAC_DEV_OUT:?set FLALAC_DEV_OUT to the folder the app was started with}"
id=$RANDOM$RANDOM
osascript -l JavaScript -e 'function run(argv) {
    ObjC.import("Foundation");
    $.NSDistributedNotificationCenter.defaultCenter.postNotificationNameObjectUserInfoDeliverImmediately(
        "com.davidepetris.flalac.dev", argv[0], $(), true);
}' "$id $*" >/dev/null
for _ in $(seq 100); do
    [ "$(cat "$FLALAC_DEV_OUT/ack" 2>/dev/null)" = "$id" ] && exit 0
    sleep 0.1
done
echo "Flalac did not answer: $*" >&2
exit 1
