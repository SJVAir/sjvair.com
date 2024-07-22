# Generated by Django 4.2.11 on 2024-07-22 19:28

import camp.utils.fields
from django.db import migrations, models
import django.utils.timezone
import phonenumber_field.modelfields


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_alter_user_email_alter_user_phone'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='date_joined',
            field=models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name='Date joined'),
        ),
        migrations.AlterField(
            model_name='user',
            name='email',
            field=camp.utils.fields.NullEmailField(blank=True, db_index=True, max_length=254, null=True, unique=True, verbose_name='Email address'),
        ),
        migrations.AlterField(
            model_name='user',
            name='full_name',
            field=models.CharField(max_length=100, verbose_name='Full name'),
        ),
        migrations.AlterField(
            model_name='user',
            name='phone',
            field=phonenumber_field.modelfields.PhoneNumberField(db_index=True, help_text='Your cell phone number for receiving air quality text alerts.', max_length=128, region=None, unique=True, verbose_name='Phone number'),
        ),
    ]
