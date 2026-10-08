# Adds the CALIFORNIA_RESTRICTED choice to Chemical.categories.
#
# Only the categories field: `makemigrations` also wants to write
# `through_fields` onto the two `commodities` M2Ms, which is unrelated
# pre-existing drift and metadata-only.
import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pesticides', '0008_chemical_preferred_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='chemical',
            name='categories',
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(
                    choices=[
                        ('biopesticide', 'Biopesticide'),
                        ('california_restricted', 'California Restricted Material'),
                        ('carcinogen', 'Carcinogen'),
                        ('cholinesterase_inhibitor', 'Cholinesterase Inhibitor'),
                        ('developmental_toxin', 'Developmental Toxin'),
                        ('fumigant', 'Fumigant'),
                        ('groundwater_contaminant', 'Groundwater Contaminant'),
                        ('oil', 'Oil'),
                        ('reproductive_toxin', 'Reproductive Toxin'),
                        ('toxic_air_contaminant', 'Toxic Air Contaminant'),
                    ],
                    max_length=32,
                ),
                blank=True, default=list, size=None, verbose_name='Categories',
            ),
        ),
    ]
