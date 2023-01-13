release: invoke release
web: gunicorn --config gunicorn-config.py camp.wsgi:application
huey_scheduler: python manage.py run_huey
huey_worker: python manage.py run_huey --no-periodic
