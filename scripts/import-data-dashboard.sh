#!/usr/bin/env bash
# Build SJVAir/data-dashboard and copy its output into dist/workspace/.
#
# Usage: import-data-dashboard.sh [SOURCE] [REF]
#   SOURCE  git URL or local repo path (default: the GitHub repo)
#   REF     branch or tag to build (default: main)
#
# A local repo path builds that repo's committed REF, so unpushed branches
# can be tested: import-data-dashboard.sh /data-dashboard foundations-5a-shipping
set -euo pipefail

SOURCE="${1:-https://github.com/SJVAir/data-dashboard}"
REF="${2:-main}"
DEST="$PWD/dist"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Building data-dashboard $REF from $SOURCE"
git clone --quiet --depth 1 --branch "$REF" "$SOURCE" "$WORK/data-dashboard"
cd "$WORK/data-dashboard"

# The build stamps its own release from the clone's commit, and serves the
# API from the page's origin: keep the deploy's values out of it. engine-strict
# makes npm refuse a Node version outside the dashboard's `engines`.
build_env=(env -u VITE_PROD_URL -u VITE_DEV_URL -u BUILD_ID -u GITHUB_SHA npm_config_engine_strict=true)
"${build_env[@]}" npm ci --include=dev
"${build_env[@]}" npm run build

if [[ ! -f dist/workspace/app.js ]]; then
    echo "Error: the build produced no dist/workspace/app.js (does $REF have the /workspace/ build?)" >&2
    exit 1
fi

mkdir -p "$DEST"
rm -rf "$DEST/workspace"
cp -r dist/workspace "$DEST/workspace"

echo "Imported data-dashboard build $(cat dist/workspace/version.json)"
