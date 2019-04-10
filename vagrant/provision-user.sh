#!/bin/bash

echo "I am `whoami`."

# Bash history completion
wget --quiet https://raw.githubusercontent.com/dmpayton/dotfiles/master/.inputrc -O ~/.inputrc

##########
## Node.js

echo
echo "Installing NVM / Node.js..."
wget -qO- https://raw.githubusercontent.com/creationix/nvm/v0.33.1/install.sh | bash

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

nvm install 10.15
npm install -g yarn
yarn install

########
# Python

echo "export PYTHONPATH=/usr/lib/python3" >> ~/.bashrc
echo "export WORKON_HOME=~/.virtualenvs" >> ~/.bashrc
echo "export PROJECT_HOME=/vagrant" >> ~/.bashrc
echo "export VIRTUALENVWRAPPER_PYTHON=/usr/bin/python3" >> ~/.bashrc
echo "source /usr/local/bin/virtualenvwrapper.sh" >> ~/.bashrc
echo "workon venv" >> ~/.bashrc

export PYTHONPATH=/usr/lib/python3
export WORKON_HOME=~/.virtualenvs
export VIRTUALENVWRAPPER_PYTHON=/usr/bin/python3
source /usr/local/bin/virtualenvwrapper.sh
mkvirtualenv venv

# chown -R vagrant:vagrant ~/.virtualenvs

#######################
# Initial project setup

cd /vagrant

# Create an initial .env if one doesn't exist
if [ ! -f .env ]; then
    cp ./vagrant/vagrant.env ./.env

    # Generate a random SECRET_KEY and update the .env
    SECRET_KEY=$(python -c "import random; print(''.join(random.SystemRandom().choice('abcdefghijklmnopqrstuvwxyz0123456789\!@#$%^&*(-_=+)') for i in range(50)))")
    sed -i -e "s/<SECRET_KEY>/${SECRET_KEY//&/\\&}/g" .env
fi

# Python dependencies
pip install -r requirements/develop.txt
pip install gdal==$(gdal-config --version) --global-option=build_ext --global-option="-I/usr/include/gdal"

# Sync the database
python manage.py migrate --no-input

#########
## Done!

echo
echo "Vagrant setup complete!"
echo "Now try logging in:"
echo "    $ vagrant ssh"
