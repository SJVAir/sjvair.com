from django.db import migrations

FLAG_NAME = 'beta_tools'
GROUP_NAME = 'Beta testers'
FLAG_NOTE = (
    'Gates the data tools under /tools/ (the pesticides and emissions explorers) '
    'and their nav links; everyone else gets a 404. Add users to the "Beta testers" '
    'group to let them in; staff and superusers are on. Set Everyone to Yes to launch.'
)


def create_flag(apps, schema_editor):
    Flag = apps.get_model('waffle', 'Flag')
    Group = apps.get_model('auth', 'Group')
    group, _ = Group.objects.get_or_create(name=GROUP_NAME)
    flag, _ = Flag.objects.get_or_create(
        name=FLAG_NAME,
        defaults={'everyone': None, 'staff': True, 'superusers': True, 'note': FLAG_NOTE},
    )
    flag.groups.add(group)


def delete_flag(apps, schema_editor):
    # The group may have members by now; only the flag goes.
    Flag = apps.get_model('waffle', 'Flag')
    Flag.objects.filter(name=FLAG_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('pesticides', '0019_amount_treated_generated_acres'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('waffle', '0004_update_everyone_nullbooleanfield'),
    ]

    operations = [
        migrations.RunPython(create_flag, delete_flag),
    ]
