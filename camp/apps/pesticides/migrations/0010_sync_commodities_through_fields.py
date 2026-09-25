# Writes `through_fields` onto the two `commodities` M2Ms, which the models
# have carried since they were written without a migration to match. Pure
# state: Django emits no SQL for a through_fields change on an M2M that
# already has an explicit through model.
#
# This began life as an untracked 0003 in the main checkout. Committing it
# there would have given Django two migrations depending on 0002 -- this
# branch's 0003 and that one -- and so two leaf nodes and a demand for a
# merge migration. It goes on the end of the chain instead.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pesticides', '0009_chemical_california_restricted_category'),
    ]

    operations = [
        migrations.AlterField(
            model_name='chemical',
            name='commodities',
            field=models.ManyToManyField(
                blank=True, related_name='chemicals', through='pesticides.PesticideUse',
                through_fields=('chemical', 'commodity'), to='pesticides.commodity',
                verbose_name='Commodities',
            ),
        ),
        migrations.AlterField(
            model_name='product',
            name='commodities',
            field=models.ManyToManyField(
                blank=True, related_name='products', through='pesticides.PesticideUse',
                through_fields=('product', 'commodity'), to='pesticides.commodity',
                verbose_name='Commodities',
            ),
        ),
    ]
