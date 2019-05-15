Air Quality Monitoring - API Server
===================================

Community Air Monitoring (CAM)

California Air Resource Board (CARB)

https://oehha.ca.gov/calenviroscreen/report/calenviroscreen-30
https://ww2.arb.ca.gov/homepage

# Setup guide

## Environment setup

1. Install [VirtualBox](https://www.virtualbox.org/) and [Vagrant](https://www.vagrantup.com/).

2. Get the code

```
host:~$ git clone git@github.com:dmpayton/aqm-server.git
host:~$ cd aqm-server
```

3. Provision the vagrant box

```
host:~/aqm-server$ vagrant up
```

This will automatically install Python dependencies and run database migrations.

4. Shell in and navigate to the project directory

```
host:~/aqm-server$ vagrant ssh
vagrant:~$ cd /vagrant
```

5. Create an admin user

```
vagrant:/vagrant$ python manage.py createsuperuser
```

6. Run the development server

```
vagrant:/vagrant$ python manage.py runserver 0:8000
```

7. Visit [localhost:8000](http://localhost:8000) in your web browser

## Other useful commands

### Running the tests

```
vagrant:/vagrant$ pytest
```

### Installing Python dependencies

```
vagrant:/vagrant$ pip install -r requirements/develop.txt
```

### Migrate the database

```
vagrant:/vagrant$ python manage.py migrate
```

### Shutting down the vagrant box

Suspend the box without fully shutting it down (makes `vagrant up` faster):

```
host:~/aqm-server$ vagrant suspend
```

Fully shut down the box:

```
host:~/aqm-server$ vagrant halt
```

### How do I access Postgres from outside my Vagrant box?

If you're wanting to access the database in your Vagrant box, e.g., with
[PgAdmin](https://www.pgadmin.org/) on your host machine, you'll need
to tell Postgres to accept external connections.

1. Tell Postgress to listen on all interfaces

    ```
    sudo sed -i "s/listen_addresses = 'localhost'/listen_addresses = '*'/g" /etc/postgresql/10/main/postgresql.conf
    ```
2. Tell Postgress to accept connections from all interfaces
    ```
    echo "host all all 0.0.0.0/0 trust" | sudo tee -a /etc/postgresql/10/main/pg_hba.conf
    ```
