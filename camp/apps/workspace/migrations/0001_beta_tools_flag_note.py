from django.db import migrations

FLAG_NAME = 'beta_tools'
NOTE = (
    'Gates the data tools under /tools/ (the pesticides and emissions explorers), '
    'the dashboard under /workspace/, and their nav links; everyone else gets a 404. '
    'Add users to the "Beta testers" group to let them in; staff and superusers are on. '
    'Set Everyone to Yes to launch.'
)
OLD_NOTE = (
    'Gates the data tools under /tools/ (the pesticides and emissions explorers) '
    'and their nav links; everyone else gets a 404. Add users to the "Beta testers" '
    'group to let them in; staff and superusers are on. Set Everyone to Yes to launch.'
)


def set_note(note):
    def apply(apps, schema_editor):
        Flag = apps.get_model('waffle', 'Flag')
        Flag.objects.filter(name=FLAG_NAME).update(note=note)
    return apply


class Migration(migrations.Migration):

    dependencies = [
        ('pesticides', '0002_beta_tools_flag'),
    ]

    operations = [
        migrations.RunPython(set_note(NOTE), set_note(OLD_NOTE)),
    ]
