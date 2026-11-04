#!/bin/sh
# Build the image and push it to Codeberg's container registry.
#
# Run from a clean checkout on a Linux host with Podman, after logging in once:
#   podman login codeberg.org      (user: KintsugiUwU, password: a Codeberg access token
#                                    with "package" read+write)
# Usage:
#   scripts/release.sh 0.1.0                      # linux/amd64
#   PLATFORMS=linux/amd64,linux/arm64 scripts/release.sh 0.1.0   # needs qemu-user-static
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

manifest="flalac-release:$version"
podman manifest rm "$manifest" >/dev/null 2>&1 || true
podman build --format docker --platform "$platforms" --manifest "$manifest" \
    --label "org.opencontainers.image.version=$version" \
    --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
    -f Containerfile .
podman manifest push --all "$manifest" "docker://$image:$version"
podman manifest push --all "$manifest" "docker://$image:latest"
echo "pushed $image:$version and :latest ($platforms)"
