release: python manage.py migrate --no-input
web: gunicorn camp.wsgi:application --bind 0.0.0.0:$PORT
huey_scheduler: python manage.py run_huey
huey_worker: python manage.py run_huey --no-periodic
