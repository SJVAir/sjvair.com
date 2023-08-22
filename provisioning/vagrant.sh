#!/usr/bin/env bash

here=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
python="python3.11"
pg_version="15"

function apt-y() {
  apt -y "$@"
}

echo "I am `whoami`."

########
## Setup
#
. "/vagrant/provisioning/setup.sh"


##########
## Python

. "/vagrant/provisioning/python.sh"


##############
## PostgreSQL

echo -e "\nInstalling PostgreSQL..."
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget -qO- https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo tee /etc/apt/trusted.gpg.d/pgdg.asc &>/dev/null
apt-y update
apt-y install "postgresql-$pg_version" "postgresql-server-dev-$pg_version" "postgresql-$pg_version-postgis-3" libpq-dev

# Create vagrant pgsql superuser with password vagrant and database vagrant_dev
su postgres -c "psql -c \"CREATE ROLE vagrant SUPERUSER LOGIN PASSWORD 'vagrant'\""
su postgres -c "createdb -E UTF8 -T template0 --locale=en_US.utf8 -O vagrant vagrant_dev"
# su postgres -c "dropdb vagrant_dev"

su postgres "$here/postgresql.sh"


#############
## Memcached

echo -e "\nInstalling Memcached..."
apt-y install memcached libmemcached-dev


########
## Redis

echo -e "\nInstalling Redis..."

add-apt-repository ppa:chris-lea/redis-server -y
apt-y update
apt-y install redis redis-server redis-tools
