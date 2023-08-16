# Generated by Django 4.2.4 on 2023-08-11 20:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_auto_20220131_0051'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='language',
            field=models.CharField(choices=[('en', 'English'), ('tl', 'Filipino'), ('hmn', 'Hmong'), ('es', 'Spanish')], default='en', max_length=5, verbose_name='Preferred Language'),
        ),
    ]
