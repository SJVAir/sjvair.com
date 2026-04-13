from django.contrib.postgres.operations import CreateExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('regions', '0002_add_place_type'),
    ]

    operations = [
        CreateExtension('pg_trgm'),
    ]
