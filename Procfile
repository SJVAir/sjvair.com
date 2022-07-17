release: python manage.py migrate --no-input
web: gunicorn --config gunicorn-config.py camp.wsgi:application
huey_scheduler: python manage.py run_huey
huey_scheduler_2: python manage.py run_huey
huey_worker: python manage.py run_huey --no-periodic
