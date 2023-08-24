#!/usr/bin/env bash

# Exit on error
set -o errexit

here=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
pod="sjvair-dev"
sjvair_pg_data="sjvair-pg-data"
sjvair_pg_runtime="sjvair-pg-runtime"
sjvair_redis_data="sjvair-redis-data"
rm_volumes=0

function check_db() {
  podman logs sjvair-pg-dev | grep "database system is ready to accept connections"
}

while test $# != 0
do
    case "$1" in
    --keep-volumes) rm_volumes=1 ;;
    esac
    shift
done

if podman pod ls | grep -q $pod; then
  echo -e "\nRemoving old pod..."
  podman pod kill $pod
  podman pod rm $pod
  if [[ $rm_volumes == 0 ]]; then
    echo -e "\nRemoving old volumes"
    podman volume rm $sjvair_pg_data
    podman volume rm $sjvair_pg_runtime
    podman volume rm $sjvair_redis_data
  fi
fi

echo -e "\nCreating dev pod: $pod"
podman pod create --name $pod --userns keep-id -p 8080:8080 -p 8000:8000 -p 35729:35729

# Create/Add postgres container
podman run -dt \
  --pod $pod \
  --name sjvair-pg-dev \
  -v $sjvair_pg_data:/var/lib/postgresql/data:U \
  -v $sjvair_pg_runtime:/var/run/postgresql:U \
  sjvair-pg \
  postgres

# Create/Add memcached container
podman run -dt \
  --pod $pod \
  --name sjvair-memcached-dev \
  docker://memcached

# Create/Add redis container
podman run -dt \
  --pod $pod \
  --name sjvair-redis-dev \
  -v $sjvair_redis_data:/data:U \
  docker://redis

# Create/Add sjvair container
podman run -dt \
  --pod $pod \
  --name sjvair-server-dev \
  -v "$here/../":/vagrant:Z \
  sjvair-server

echo -e "\nRestarting pod..."
podman pod stop $pod
podman pod start $pod

# Sync the database
if [[ $rm_volumes == 0 ]]; then
  if [ -z "$(check_db)" ]; then
    printf "\nWaiting for database"
    while [ -z "$(check_db)" ]; do
      printf '.'
    done
    printf "\n"
  fi
  echo -e "\nRunning initial migrations..."
  podman exec --tty sjvair-server-dev bash -ilc "./manage.py migrate --no-input"
fi
