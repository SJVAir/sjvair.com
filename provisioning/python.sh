#!/usr/bin/env bash

python="python3.11"

function apt-y() {
  apt -y "$@"
}

function apt-install() {
  apt-y install "$@"
}

echo -e "\nInstalling Python..."

# Add Deadsnakes PPA for lattest version of python
sudo add-apt-repository ppa:deadsnakes/ppa -y
apt-y update
apt-y upgrade

apt-install "$python-full" "$python-dev"
ln -s "/usr/bin/$python" /usr/local/bin/python

# pip
echo -e "\nInstalling pip..."
wget https://bootstrap.pypa.io/get-pip.py -O - | "$python"

# virtualenv
echo -e "\nInstalling virtualenv + virtualenvwrapper..."

pip install virtualenv virtualenvwrapper
