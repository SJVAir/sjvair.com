# Generated by Django 3.2.5 on 2021-08-10 06:08

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import django_smalluuid.models
import model_utils.fields


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('monitors', '0017_auto_20210312_1234'),
    ]

    operations = [
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('id', django_smalluuid.models.SmallUUIDField(db_index=True, default=django_smalluuid.models.UUIDDefault(), editable=False, primary_key=True, serialize=False, unique=True, verbose_name='ID')),
                ('level', models.CharField(choices=[('unhealthy_sensitive', 'Unhealthy for Sensitive Groups'), ('unhealthy', 'Unhealthy'), ('very_unhealthy', 'Very Unhealthy'), ('hazardous', 'Hazardous')], max_length=25)),
                ('monitor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='subscriptions', to='monitors.monitor')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='subscriptions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['monitor__name'],
            },
        ),
        migrations.AddConstraint(
            model_name='subscription',
            constraint=models.UniqueConstraint(fields=('user', 'monitor'), name='user_subscriptions'),
        ),
    ]