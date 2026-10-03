import django.db.models.deletion

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('regions', '0006_location'),
    ]

    operations = [
        migrations.RenameField(
            model_name='location',
            old_name='city',
            new_name='city_name',
        ),
        migrations.RenameField(
            model_name='location',
            old_name='district',
            new_name='school_district',
        ),
        migrations.AlterField(
            model_name='location',
            name='city_name',
            field=models.CharField(blank=True, max_length=100, verbose_name='City Name'),
        ),
        migrations.AlterField(
            model_name='location',
            name='county',
            field=models.ForeignKey(blank=True, limit_choices_to={'type': 'county'}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='county_locations', to='regions.region', verbose_name='County'),
        ),
        migrations.AlterField(
            model_name='location',
            name='school_district',
            field=models.ForeignKey(blank=True, limit_choices_to={'type': 'school_district'}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='district_locations', to='regions.region', verbose_name='School District'),
        ),
        migrations.AddField(
            model_name='location',
            name='city',
            field=models.ForeignKey(blank=True, limit_choices_to={'type__in': ['city', 'cdp']}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='city_locations', to='regions.region', verbose_name='City'),
        ),
        migrations.AddField(
            model_name='location',
            name='zipcode',
            field=models.ForeignKey(blank=True, limit_choices_to={'type': 'zipcode'}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='zipcode_locations', to='regions.region', verbose_name='ZIP Code'),
        ),
    ]
