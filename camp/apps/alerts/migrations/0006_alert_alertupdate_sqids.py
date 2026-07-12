from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import camp.apps.entries.fields
import model_utils.fields


class Migration(migrations.Migration):
    # This migration re-adds notification.alert_update as NOT NULL, which
    # only succeeds because 0005_notification (this same PR) guarantees the
    # Notification table is empty when this runs. Deploy 0005 and 0006
    # together in the same release — if 0005 ever goes live on its own
    # first and real Notification rows are created, this migration will
    # fail with a NOT NULL constraint violation.

    dependencies = [
        ('monitors', '0017_auto_20210312_1234'),
        ('alerts', '0005_notification'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='alert',
            name='latest',
        ),
        migrations.RemoveField(
            model_name='notification',
            name='alert_update',
        ),
        migrations.DeleteModel(
            name='AlertUpdate',
        ),
        migrations.DeleteModel(
            name='Alert',
        ),
        migrations.CreateModel(
            name='Alert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('entry_type', camp.apps.entries.fields.EntryTypeField(max_length=50)),
                ('start_time', models.DateTimeField()),
                ('end_time', models.DateTimeField(blank=True, null=True)),
                ('monitor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='alerts', to='monitors.monitor')),
            ],
            options={
                'ordering': ['-start_time'],
            },
        ),
        migrations.CreateModel(
            name='AlertUpdate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('timestamp', models.DateTimeField(default=django.utils.timezone.now)),
                ('level', models.CharField(max_length=25)),
                ('alert', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='updates', to='alerts.alert')),
            ],
            options={
                'ordering': ['timestamp'],
                'get_latest_by': 'timestamp',
            },
        ),
        migrations.AddField(
            model_name='alert',
            name='latest',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='alerts.alertupdate'),
        ),
        migrations.AddField(
            model_name='notification',
            name='alert_update',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to='alerts.alertupdate'),
        ),
    ]
