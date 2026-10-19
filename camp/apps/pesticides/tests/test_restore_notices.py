import csv
import io
from datetime import datetime, timezone

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from camp.apps.pesticides.management.commands.restore_spraydays_notices import EXPORT_SQL
from camp.apps.pesticides.models import Chemical, PesticideNotice, Product


def export_csv():
    """What `\\copy (EXPORT_SQL) TO ... WITH CSV HEADER` writes, built here through the same query."""
    with connection.cursor() as cursor:
        cursor.execute(EXPORT_SQL)
        header = [column.name for column in cursor.description]
        rows = cursor.fetchall()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow(['' if value is None else value for value in row])
    return out.getvalue()


class RestoreNoticesTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        self.product = Product.objects.get(pk=1)
        self.chemical = Chemical.objects.get(pk=1)
        self.past = PesticideNotice.objects.create(
            application_id=111, comtrs='10M14S20E01', mtrs_id=9101, county_id=9001,
            point=Point(-119.8, 36.7, srid=4326),
            scheduled_application=datetime(2025, 6, 1, 14, tzinfo=timezone.utc),
            treated_amount=40.5, treated_units='A', application_method='Ground',
        )
        self.past.products.set([self.product])
        self.past.chemicals.set([self.chemical])
        PesticideNotice.objects.filter(pk=self.past.pk).update(created=datetime(2025, 5, 20, tzinfo=timezone.utc))
        self.bare = PesticideNotice.objects.create(
            application_id=222, comtrs='10M14S20E02',
            scheduled_application=datetime(2025, 7, 1, 14, tzinfo=timezone.utc),
        )

    def restore(self, text):
        path = self.tmp_path(text)
        out = io.StringIO()
        call_command('restore_spraydays_notices', path=path, stdout=out)
        return out.getvalue()

    def tmp_path(self, text):
        import tempfile
        handle = tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False)
        handle.write(text)
        handle.close()
        return handle.name

    def test_round_trip_after_a_reset_relinks_by_cdpr_codes(self):
        exported = export_csv()
        total = PesticideNotice.objects.count()  # the fixture's notices and these two
        # The reset: notices gone, and the re-import gives the product a new id.
        PesticideNotice.objects.all().delete()
        prodno = self.product.prodno
        fields = {f.attname: getattr(self.product, f.attname) for f in Product._meta.concrete_fields if f.attname not in ('id', 'sqid')}
        self.product.delete()
        new_product = Product.objects.create(**fields)
        assert new_product.pk != 1 and new_product.prodno == prodno

        output = self.restore(exported)
        assert f'Restored {total} notices; skipped 0' in output
        assert PesticideNotice.objects.count() == total

        notice = PesticideNotice.objects.get(application_id=111)
        assert list(notice.products.all()) == [new_product]
        assert list(notice.chemicals.all()) == [self.chemical]
        assert (notice.mtrs_id, notice.county_id, notice.comtrs) == (9101, 9001, '10M14S20E01')
        assert notice.scheduled_application == datetime(2025, 6, 1, 14, tzinfo=timezone.utc)
        assert notice.created == datetime(2025, 5, 20, tzinfo=timezone.utc)
        assert (notice.treated_amount, notice.treated_units, notice.application_method) == (40.5, 'A', 'Ground')
        assert round(notice.point.x, 4) == -119.8 and round(notice.point.y, 4) == 36.7

        bare = PesticideNotice.objects.get(application_id=222)
        assert bare.mtrs_id is None and bare.point is None and bare.treated_amount is None
        assert not bare.products.exists()

    def test_a_notice_fetched_again_keeps_its_live_copy(self):
        exported = export_csv()
        total = PesticideNotice.objects.count()
        PesticideNotice.objects.filter(application_id=222).delete()
        PesticideNotice.objects.filter(application_id=111).update(treated_amount=99)
        output = self.restore(exported)
        assert f'Restored 1 notices; skipped {total - 1}' in output
        assert PesticideNotice.objects.get(application_id=111).treated_amount == 99

    def test_a_rebuild_relinks_sections_and_counties_by_comtrs(self):
        # A rebuild from scratch re-imports regions under new ids, so the
        # exported ids point at nothing; the COMTRS code still names the place.
        exported = export_csv().replace(',9101,9001,', ',88742,2,')
        PesticideNotice.objects.all().delete()
        self.restore(exported)
        notice = PesticideNotice.objects.get(application_id=111)
        assert (notice.mtrs_id, notice.county_id) == (9101, 9001)

    def test_a_spraydays_comtrs_without_a_meridian_resolves(self):
        # SprayDays writes COMTRS without the meridian letter PUR uses.
        PesticideNotice.objects.filter(application_id=111).update(comtrs='1014S20E01')
        exported = export_csv().replace(',9101,9001,', ',88742,2,')
        PesticideNotice.objects.all().delete()
        self.restore(exported)
        notice = PesticideNotice.objects.get(application_id=111)
        assert (notice.mtrs_id, notice.county_id) == (9101, 9001)

    def test_a_comtrs_with_no_local_section_is_reported(self):
        PesticideNotice.objects.filter(application_id=111).update(comtrs='1099S99E01')
        exported = export_csv()
        PesticideNotice.objects.all().delete()
        output = self.restore(exported)
        notice = PesticideNotice.objects.get(application_id=111)
        assert notice.mtrs_id is None and notice.county_id == 9001
        assert '1 notice(s) with no matching section' in output

    def test_codes_missing_after_the_reimport_are_reported(self):
        exported = export_csv()
        PesticideNotice.objects.all().delete()
        Chemical.objects.filter(pk=1).delete()
        output = self.restore(exported)
        assert '1 chemical code(s) not in the database' in output
        assert not PesticideNotice.objects.get(application_id=111).chemicals.exists()
