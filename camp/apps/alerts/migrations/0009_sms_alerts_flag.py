from django.db import migrations

FLAG_NAME = 'sms_alerts'
FLAG_NOTE = (
    'Gates SMS alert and reminder texts. Only users enabled here (users, groups, '
    'staff or superusers) are texted. Set Everyone to Yes to open it to all subscribers.'
)


def create_flag(apps, schema_editor):
    Flag = apps.get_model('waffle', 'Flag')
    Flag.objects.get_or_create(name=FLAG_NAME, defaults={'everyone': None, 'note': FLAG_NOTE})


def delete_flag(apps, schema_editor):
    Flag = apps.get_model('waffle', 'Flag')
    Flag.objects.filter(name=FLAG_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('alerts', '0008_subscription_notification_state'),
        ('waffle', '0004_update_everyone_nullbooleanfield'),
    ]

    operations = [
        migrations.RunPython(create_flag, delete_flag),
    ]
