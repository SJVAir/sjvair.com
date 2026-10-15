from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ceidars', '0001_initial'),
    ]

    # Drops the old tables; the data is re-imported into camp.apps.emissions.
    operations = [
        migrations.DeleteModel(name='EmissionsRecord'),
        migrations.DeleteModel(name='Facility'),
    ]
