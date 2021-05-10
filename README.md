CAMP Server
===========

California Air Resource Board (CARB)

https://oehha.ca.gov/calenviroscreen/report/calenviroscreen-30
https://ww2.arb.ca.gov/homepage
https://publiclab.org/questions/samr/04-07-2019/how-to-interpret-pms5003-sensor-values

```
from django.core.management import call_command
Sensor.objects.all().delete()
call_command('loaddata', 'fixtures/sensors.yaml')
```

# Setup guide

## Environment setup

1. Install [VirtualBox](https://www.virtualbox.org/) and [Vagrant](https://www.vagrantup.com/).

2. Get the code

```
host:~/dev$ git clone git@github.com:SJVAir/sjvair.com.git
host:~/dev$ cd sjvair.com
```

3. Provision the vagrant box

```
host:~/dev/sjvair.com$ vagrant up
```

This will automatically install Python dependencies and run database migrations.

4. Shell in and navigate to the project directory

```
host:~/dev/sjvair.com$ vagrant ssh
vagrant:~$ cd /vagrant
```

5. Create an admin user

```
vagrant:/vagrant$ python manage.py createsuperuser
```

6a. Build the front-end

```
vagrant:/vagrant$ invoke build
```

6b. Run the development server

```
vagrant:/vagrant$ python manage.py runserver 0:8000
```

6c. Run the task workers

```
vagrant:/vagrant$ python manage.py run_huey
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
host:~/dev/sjvair.com$ vagrant suspend
```

Fully shut down the box:

```
host:~/dev/sjvair.com$ vagrant halt
```

### Help! I only see sensors on the map the first time I run `vagrant up`
This happens because of a gap in time and data. The server will try to backfill sensor entries to the last point in time in which it was running. If you have the patience, you can wait for the server to process all of that missing data, and then everything should work as expected. For the rest of us who can't wait, we can start fresh by flushing the task queue and deleting the old sensor entries like so:

```
host:~dev/sjvair.com$ python manage.py clear_huey_and_entries
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
