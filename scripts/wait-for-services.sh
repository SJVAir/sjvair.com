#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
until pg_isready -h db -p 5432 -U sjvair -d sjvair; do
  sleep 1
done

echo "Waiting for Redis..."
until redis-cli -h redis ping | grep -q PONG; do
  sleep 1
done

echo "Waiting for Memcached..."
until nc -vz memcached 11211 > /dev/null; do
  sleep 1
done

echo "All services ready!"

exec "$@"
