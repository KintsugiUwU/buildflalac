#!/bin/sh
# Publish a version: check the git checkout, tag it, build the image and push it to Codeberg.
#
#   scripts/release.sh 0.1.0
#
# The build runs locally, or on RELEASE_HOST over ssh (e.g. RELEASE_HOST=user@nas), which only
# needs Podman and a one-time `podman login codeberg.org` (Codeberg token with package write).
# PLATFORMS=linux/amd64,linux/arm64 also builds arm64 (the build host needs qemu-user-static).
set -eu

version="${1:?usage: scripts/release.sh <version>, e.g. 0.1.0}"
image="${IMAGE:-codeberg.org/kintsugiuwu/flalac}"
platforms="${PLATFORMS:-linux/amd64}"

if [ -n "$(git status --porcelain)" ]; then
    echo "release: the checkout has uncommitted changes; commit them first" >&2
    exit 1
fi
expected="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
if [ "$version" != "$expected" ]; then
    echo "release: pyproject.toml says $expected, not $version" >&2
    exit 1
fi
revision="$(git rev-parse HEAD)"
vars="VERSION=$version IMAGE=$image PLATFORMS=$platforms REVISION=$revision"

if [ -n "${RELEASE_HOST:-}" ]; then
    git archive --format=tar HEAD | ssh "$RELEASE_HOST" \
        "d=\$(mktemp -d) && tar -x -C \"\$d\" && cd \"\$d\" && $vars sh scripts/build-and-push.sh; rc=\$?; rm -rf \"\$d\"; exit \$rc"
else
    env $vars sh scripts/build-and-push.sh
fi

if ! git rev-parse -q --verify "refs/tags/v$version" >/dev/null; then
    git tag -a "v$version" -m "flalac $version"
    git push origin "v$version"
fi
