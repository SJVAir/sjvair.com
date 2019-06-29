release: python manage.py migrate --no-input
web: gunicorn ordrslip.wsgi:application --bind 0.0.0.0:$PORT
huey: python manage.py run_huey
