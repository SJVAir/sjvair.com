#!/usr/bin/env bash

function apty() {
  apt -y "$@"
}

function apt-install() {
  apty install "$@"
}

# Ensure everything is up to date
echo -e "\nUpdating the system..."
apty update
apty upgrade

# Build tools and pre-reqs
echo -e "\nInstalling developer tools..."
apt-install build-essential libjpeg-dev libssl-dev libtiff5-dev zlib1g-dev curl

# Geospatial requirements
echo -e "\nInstalling geospatial libraries..."
apt-install binutils libproj-dev libgdal-dev
