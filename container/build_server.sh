#!/usr/bin/env bash

# Exit on error
set -o errexit

install_path="/vagrant";
project_path=$(pwd)
container=$(buildah from sjvair-server-base:latest)

function bexec() {
  buildah run --terminal -e DEBIAN_FRONTEND=noninteractive $container -- bash -ilc "$@"
}

# Switch to vagrant user
buildah config --user vagrant $container

# Configure user
bexec "provisioning/user.sh"

# Install other packages required the this environment
#bexec "pip install ndg-httpsclient pyansi"

# Save in Docker format for compatibility
buildah commit --format docker $container sjvair-server:latest
