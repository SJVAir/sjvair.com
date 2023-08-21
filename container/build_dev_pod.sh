#!/usr/bin/env bash

# Exit on error
set -o errexit

pod="sjvair-dev"
pg_volume="sjvair-pg-data"

if podman pod ls | grep -q $pod; then
  echo -e "\nRemoving old pod..."
  podman pod kill $pod
  podman pod rm $pod
  podman volume rm $pg_volume
fi

echo -e "\nCreating dev pod: $pod"
podman pod create --name $pod -p 8080:8080 -p 8000:8000 -p 35729:35729

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
  sjvair-server

podman pod stop $pod
podman pod start $pod
# Sync the database
podman exec --tty sjvair-server-dev bash -ilc "./manage.py migrate --no-input"
