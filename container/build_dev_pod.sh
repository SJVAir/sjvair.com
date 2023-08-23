#!/usr/bin/env bash

# Exit on error
set -o errexit

here=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
pod="sjvair-dev"
pg_volume="sjvair-pg-data"
rm_volume=0

while test $# != 0
do
    case "$1" in
    --keep-volume) rm_volume=1 ;;
    esac
    shift
done

if podman pod ls | grep -q $pod; then
  echo -e "\nRemoving old pod..."
  podman pod kill $pod
  podman pod rm $pod
  if [[ $rm_volume == 0 ]]; then
    echo -e "\nRemoving old Postgres volume"
    podman volume rm $pg_volume
  fi
fi

echo -e "\nCreating dev pod: $pod"
podman pod create --name $pod --userns=keep-id -p 8080:8080 -p 8000:8000 -p 35729:35729

# Create/Add postgres container
podman run -dt \
  --pod $pod \
  --name sjvair-pg-dev \
  -v $pg_volume:/var/lib/postgresql/data \
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
  docker://redis

# Create/Add sjvair container
podman run -dt \
  --pod $pod \
  --name sjvair-server-dev \
  -v "$here/../":/vagrant:Z \
  sjvair-server

echo -e "Restarting pod..."
podman pod stop $pod
podman pod start $pod

# Sync the database
if [[ $rm_volume == 0 ]]; then
  echo -e "Running initial migrations..."
  podman exec --tty sjvair-server-dev bash -ilc "./manage.py migrate --no-input"
fi
