"""
Copy the ten named toxic air contaminant columns of EmissionsRecord into the
long ToxicEmission table, behind placeholder ToxicPollutant rows (CARB id and
a curated name; no health values -- import_health_values adds them). A
placeholder is created only for a column that has at least one non-null
value, so a fresh (empty) database gets none. About 130k records; under a
minute. Reverse is a no-op: 0009's reverse re-adds the empty columns, and the
ToxicEmission rows stay.
"""
from django.db import migrations
from django.utils.text import slugify

# EmissionsRecord field -> (CARB pollutant id, display name). The ids are the
# undashed CAS numbers import_ceidars used to request each column.
NAMED_TOXICS = {
    'acetaldehyde': ('75070', 'Acetaldehyde'),
    'benzene': ('71432', 'Benzene'),
    'butadiene': ('106990', '1,3-Butadiene'),
    'carbon_tetrachloride': ('56235', 'Carbon tetrachloride'),
    'chromium_hexavalent': ('18540299', 'Hexavalent chromium'),
    'dichlorobenzene': ('106467', 'para-Dichlorobenzene'),
    'formaldehyde': ('50000', 'Formaldehyde'),
    'methylene_chloride': ('75092', 'Methylene chloride'),
    'naphthalene': ('91203', 'Naphthalene'),
    'perchloroethylene': ('127184', 'Perchloroethylene'),
}
BATCH = 5000


def cas_number(carb_id):
    return f'{carb_id[:-3]}-{carb_id[-3:-1]}-{carb_id[-1]}'


def copy_named_toxics(apps, schema_editor):
    ToxicPollutant = apps.get_model('emissions', 'ToxicPollutant')
    ToxicEmission = apps.get_model('emissions', 'ToxicEmission')
    EmissionsRecord = apps.get_model('emissions', 'EmissionsRecord')

    # Only create a placeholder for a column that actually has data to copy;
    # a fresh (empty) database gets none.
    fields = [
        field for field in NAMED_TOXICS
        if EmissionsRecord.objects.filter(**{f'{field}__isnull': False}).exists()
    ]
    pollutants = {}
    for field in fields:
        carb_id, name = NAMED_TOXICS[field]
        pollutants[field], _ = ToxicPollutant.objects.get_or_create(
            carb_id=carb_id,
            defaults={'cas_number': cas_number(carb_id), 'name': name, 'slug': slugify(name), 'kind': 'toxic'},
        )

    batch = []
    rows = EmissionsRecord.objects.order_by('pk').values('facility_id', 'year', *fields).iterator(chunk_size=BATCH)
    for row in rows:
        for field in fields:
            if row[field] is None:
                continue
            batch.append(ToxicEmission(
                facility_id=row['facility_id'], year=row['year'], pollutant=pollutants[field], lbs=row[field],
            ))
        if len(batch) >= BATCH:
            ToxicEmission.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        ToxicEmission.objects.bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('emissions', '0007_toxics_long_format'),
    ]

    operations = [
        migrations.RunPython(copy_named_toxics, migrations.RunPython.noop),
    ]
