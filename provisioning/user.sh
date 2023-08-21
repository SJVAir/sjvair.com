#!/bin/bash

function setup_node() {
  echo -e "\nInstalling NVM / Node.js..."
  wget -qO- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.4/install.sh | bash

  export NVM_DIR="$HOME/.nvm"
  [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

  nvm install 16.13.0
  npm install -g yarn

  # Node dependencies
  yarn install
}

function setup_python() {
  echo "export PYTHONPATH=/usr/lib/python3.11" >> ~/.bashrc
  echo "export WORKON_HOME=~/.virtualenvs" >> ~/.bashrc
  echo "export PROJECT_HOME=/vagrant" >> ~/.bashrc
  echo "export VIRTUALENVWRAPPER_PYTHON=/usr/bin/python3.11" >> ~/.bashrc
  echo "source /usr/local/bin/virtualenvwrapper.sh" >> ~/.bashrc
  echo "workon venv" >> ~/.bashrc

  export PYTHONPATH=/usr/lib/python3.11
  export WORKON_HOME=~/.virtualenvs
  export VIRTUALENVWRAPPER_PYTHON=/usr/bin/python3.11
  source /usr/local/bin/virtualenvwrapper.sh
  mkvirtualenv venv

  # Python dependencies
  pip install -r requirements/develop.txt
  pip install gdal==$(gdal-config --version) \
    --global-option=build_ext \
    --global-option="-I/usr/include/gdal"
}

function setup_project() {
  # Create an initial .env if one doesn't exist
  if [ ! -f .env ]; then
      cp ./provisioning/env.template ./.env

      # Generate a random SECRET_KEY and update the .env
      SECRET_KEY=$(python -c "import random; print(''.join(random.SystemRandom().choice('abcdefghijklmnopqrstuvwxyz0123456789\!@#$%^&*(-_=+)') for i in range(50)))")
      sed -i -e "s/<SECRET_KEY>/${SECRET_KEY//&/\\&}/g" .env
  fi
}

echo "I am `whoami`."

# Bash history completion
wget --quiet https://raw.githubusercontent.com/dmpayton/dotfiles/master/.inputrc -O ~/.inputrc

setup_project
setup_node
setup_python
