#!/bin/sh
# Build the image in the current folder and push it. Called by release.sh, locally or on the
# build host; needs Podman and `podman login` for the registry.
set -eu

: "${VERSION:?}" "${IMAGE:?}" "${PLATFORMS:?}" "${REVISION:?}"
manifest="flalac-release:$VERSION"
podman manifest rm "$manifest" >/dev/null 2>&1 || true
podman build --format docker --platform "$PLATFORMS" --manifest "$manifest" \
    --label "org.opencontainers.image.version=$VERSION" \
    --label "org.opencontainers.image.revision=$REVISION" \
    -f Containerfile .
podman manifest push --all "$manifest" "docker://$IMAGE:$VERSION"
podman manifest push --all "$manifest" "docker://$IMAGE:latest"
podman manifest rm "$manifest" >/dev/null 2>&1 || true
echo "pushed $IMAGE:$VERSION and :latest ($PLATFORMS)"
