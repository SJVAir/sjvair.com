#!/bin/bash

echo "I am `whoami`."

########
## Setup

# Ensure everything is up to date
echo
echo "Updating the system..."
apt-get update -y
apt-get upgrade -y


# Build tools and pre-reqs
echo
echo "Installing developer tools..."
apt-get install -y build-essential libjpeg-dev libssl-dev libtiff5-dev zlib1g-dev curl

# Geospatial requirements
echo
echo "Installing geospatial libraries..."
apt-get install -y binutils libproj-dev libgdal-dev

##########
## Python

echo
echo "Installing Python..."
apt-get install -y python3 python3-dev
ln -s /usr/bin/python3 /usr/local/bin/python

# pip
echo "Installing pip..."
wget https://bootstrap.pypa.io/get-pip.py -O - | python3

# virtualenv
echo "Installing virtualenv + virtualenvwrapper..."

pip install virtualenv virtualenvwrapper

##############
## PostgreSQL

echo "Installing PostgreSQL..."
apt-get install -y postgresql-12 postgresql-server-dev-12 postgresql-12-postgis-3 libpq-dev

# Create vagrant pgsql superuser with password vagrant and database vagrant_dev
su postgres -c "psql -c \"CREATE ROLE vagrant SUPERUSER LOGIN PASSWORD 'vagrant'\""
su postgres -c "createdb -E UTF8 -T template0 --locale=en_US.utf8 -O vagrant vagrant_dev"
# su postgres -c "dropdb vagrant_dev"

# Install PostGIS
su postgres -c "psql -c \"CREATE EXTENSION postgis\""


#############
## Memcached

echo
echo "Installing Memcached..."
apt-get install -y memcached libmemcached-dev


########
## Redis

echo
echo "Installing Redis..."

add-apt-repository ppa:chris-lea/redis-server
apt-get update
apt-get install redis redis-server redis-tools
