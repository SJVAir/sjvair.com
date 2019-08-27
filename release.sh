invoke build
python manage.py collectstatic --no-input
python manage.py migrate --no-input
