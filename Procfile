release: invoke release
web: gunicorn --config gunicorn-config.py camp.wsgi:application
huey_primary_scheduler: python manage.py djangohuey --queue primary
huey_primary_worker: python manage.py djangohuey --queue primary --no-periodic
huey_secondary_worker: python manage.py djangohuey --queue secondary --no-periodic
