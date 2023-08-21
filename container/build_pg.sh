#!/usr/bin/env bash

# Exit on error
set -o errexit

here=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
install_path="/vagrant";
project_path=$(pwd)
container=$(buildah from docker://postgres:15)
pg_version="15"

function brun() {
  buildah run -e DEBIAN_FRONTEND=noninteractive $container -- "$@"
}

brun apt update
brun apt upgrade
brun apt-get install -y \
  "postgresql-server-dev-$pg_version" \
  "postgresql-$pg_version-postgis-3" \
  libpq-dev

buildah config \
  -e POSTGRES_USER="vagrant" \
  -e POSTGRES_PASSWORD="vagrant" \
  -e POSTGRES_DB="vagrant_dev" \
  $container

buildah copy $container \
  "$here/../provisioning/postgresql.sh" \
  /docker-entrypoint-initdb.d/10_postgis.sh

# Save in Docker format for compatibility
buildah commit --format docker $container sjvair-pg:latest
