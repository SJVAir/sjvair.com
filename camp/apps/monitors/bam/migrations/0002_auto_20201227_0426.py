# Generated by Django 3.1.1 on 2020-12-27 04:26

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('bam', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='bam1022',
            options={'verbose_name': 'BAM 1022'},
        ),
        migrations.RemoveField(
            model_name='bam1022',
            name='auth_key',
        ),
    ]
