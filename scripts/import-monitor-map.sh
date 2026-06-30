#!/usr/bin/env bash
set -euo pipefail

cleanup() {
    if [ -d "/tmp/monitor-map" ]; then
        echo "Running cleanup..."
        cd /tmp
        rm -rf ./monitor-map
    fi
}

trap "cleanup" EXIT

if [[ -z "$1" ]]; then
    echo "Usage: $0 <local|production>"
    exit 1
elif [[ "$1" != "local" && "$1" != "production" ]]; then
    echo "Error: Invalid argument '$1'. Please use 'local' or 'production'."
    exit 1
fi

DEST="$PWD/dist"

if [ -d "$DEST/monitor-map" ]; then
    rm -rf "$DEST/monitor-map"
fi

cd /tmp
git clone https://github.com/SJVAir/monitor-map
cd ./monitor-map

command -v npm && npm i

case "$1" in
"local")
    npm run build:local
    ;;
"production")
    npm run build
    ;;
esac

cp -r dist/monitor-map $DEST
