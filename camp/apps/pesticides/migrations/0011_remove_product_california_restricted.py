# Drops Product.california_restricted. Restricted materials are 3 CCR 6400,
# which names active ingredients, so the status lives on Chemical.categories
# (CALIFORNIA_RESTRICTED) and a product is restricted when one of its
# ingredients is. Nothing ever set this column: import_pur looked for a
# RESTRICTED.txt that CDPR doesn't publish, so it is False on all 69,648
# rows and no data is lost.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('pesticides', '0010_sync_commodities_through_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='product',
            name='california_restricted',
        ),
    ]
