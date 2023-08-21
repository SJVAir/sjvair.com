#!/usr/bin/env bash

# Exit on error
set -o errexit

install_path="/vagrant";
project_path=$(pwd)
container=$(buildah from docker://ubuntu:jammy)

function brun() {
  buildah run -e DEBIAN_FRONTEND=noninteractive $container -- "$@"
}

function bexec() {
  buildah run --terminal -e DEBIAN_FRONTEND=noninteractive $container -- bash -ilc "$@"
}

# Image meta
buildah config --label maintainer="Derek Payton & Alexander McCormick" $container

# Set environment variables
buildah config -e TZ=Etc/UTC -e REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt $container

# Update the system
brun apt update
brun apt -y upgrade

# Install vagrant setup script deps
brun apt -y install git software-properties-common sudo wget

# Install bonus tools
brun apt -y install dvtm

# Configure sudo to be passwordless
brun sh -c "echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers"

# Create the vagrant user
brun useradd -m vagrant -p vagrant -G sudo

# Copy over project contents
buildah copy --chown vagrant:vagrant \
  --contextdir $project_path \
  $container \
  $project_path $install_path

# Set default directory to the install path
buildah config --workingdir $install_path $container

# Run provision-root.sh
bexec "provisioning/setup.sh"
bexec "provisioning/python.sh"

# Save in Docker format for compatibility
buildah commit --format docker $container sjvair-server-base:latest
