from django.db import migrations, models


def acres_from(amount, unit):
    # Frozen copy of models.acres_from as of this migration.
    return models.Case(
        models.When(**{unit: 'A'}, then=models.F(amount)),
        models.When(**{unit: 'S'}, then=models.F(amount) / models.Value(43560.0)),
        default=None,
        output_field=models.FloatField(),
    )


class Migration(migrations.Migration):
    """
    CDPR's acre_treated / acre_planted are in whatever unit unit_treated /
    unit_planted names (square feet, cubic feet, pounds, tons...), so the
    columns holding them are renamed amount_*, and acres_* become stored
    generated columns: the amount in acres when the unit is an area, else
    NULL. Adding them rewrites the table once; only import_pur writes it.
    Rebuild the rollup afterwards (`rebuild_pesticide_rollup --all`).
    """

    dependencies = [
        ('pesticides', '0018_product_restricted_flags'),
    ]

    operations = [
        migrations.RenameField('pesticideuse', 'acres_planted', 'amount_planted'),
        migrations.RenameField('pesticideuse', 'acres_treated', 'amount_treated'),
        migrations.AlterField(
            model_name='pesticideuse',
            name='amount_planted',
            field=models.FloatField(blank=True, null=True, verbose_name='Amount Planted'),
        ),
        migrations.AlterField(
            model_name='pesticideuse',
            name='amount_treated',
            field=models.FloatField(blank=True, null=True, verbose_name='Amount Treated'),
        ),
        migrations.AddField(
            model_name='pesticideuse',
            name='acres_planted',
            field=models.GeneratedField(
                db_persist=True,
                expression=acres_from('amount_planted', 'unit_planted'),
                output_field=models.FloatField(blank=True, null=True, verbose_name='Acres Planted'),
            ),
        ),
        migrations.AddField(
            model_name='pesticideuse',
            name='acres_treated',
            field=models.GeneratedField(
                db_persist=True,
                expression=acres_from('amount_treated', 'unit_treated'),
                output_field=models.FloatField(blank=True, null=True, verbose_name='Acres Treated'),
            ),
        ),
    ]
