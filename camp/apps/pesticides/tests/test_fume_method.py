import io
import zipfile
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides import stats
from camp.apps.pesticides.management.commands.import_pur import Command
from camp.apps.pesticides.models import Chemical, FumigationMethod, PesticideUse, Product
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.pesticides.tests.test_import_pur import lookup_dir
from camp.apps.regions.models import Region

METHODS = (
    'fume_cd,fume_method,fume_active,fume_create_dt,fume_end_dt\n'
    '1107,"Tarpaulin/Deep/Broadcast [6447.3(a)(5)]",Y,23-OCT-2008,\n'
    '1290,"1,3-Dichloropropene - Other label method [6448]",N,23-OCT-2008,31-DEC-2023\n'
)
PUR_HEADER = 'year,use_no,record_id,county_cd,aer_gnd_ind,fume_cd,pre_plant\n'


class FumigationMethodModelTests(TestCase):
    def test_str_is_the_name_and_short_name_drops_the_citation(self):
        method = FumigationMethod.objects.create(code=1107, name='Tarpaulin/Deep/Broadcast [6447.3(a)(5)]')
        assert str(method) == 'Tarpaulin/Deep/Broadcast [6447.3(a)(5)]'
        assert method.short_name == 'Tarpaulin/Deep/Broadcast'
        assert method.sqid
        assert method.active is True

    def test_short_name_leaves_an_uncited_name_alone(self):
        method = FumigationMethod(code=1, name='Something else')
        assert method.short_name == 'Something else'


class FumigationMethodImportTests(TestCase):
    def test_lookup_imports_codes_and_activity(self):
        Command()._import_fumigation_methods(lookup_dir(FUMIGATION_METHODS__txt=METHODS))
        assert FumigationMethod.objects.get(code=1107).name == 'Tarpaulin/Deep/Broadcast [6447.3(a)(5)]'
        assert FumigationMethod.objects.get(code=1107).active is True
        old = FumigationMethod.objects.get(code=1290)
        assert old.name == '1,3-Dichloropropene - Other label method [6448]'
        assert old.active is False

    def test_lookup_is_idempotent_and_updates_in_place(self):
        directory = lookup_dir(FUMIGATION_METHODS__txt=METHODS)
        Command()._import_fumigation_methods(directory)
        pk = FumigationMethod.objects.get(code=1107).pk
        Command()._import_fumigation_methods(directory)
        assert FumigationMethod.objects.count() == 2
        assert FumigationMethod.objects.get(code=1107).pk == pk

    def test_missing_file_is_skipped(self):
        Command()._import_fumigation_methods(lookup_dir())
        assert FumigationMethod.objects.count() == 0


class FumeCodePassTests(TestCase):
    def setUp(self):
        self.fresno = Region.objects.create(
            name='Fresno County', slug='fresno', type=Region.Type.COUNTY, external_id='06019')
        self.tarp = FumigationMethod.objects.create(code=1107, name='Tarpaulin/Deep/Broadcast [6447.3(a)(5)]')
        self.other = FumigationMethod.objects.create(code=1290, name='Other label method [6448]')
        # use_no 1 has two ingredient rows; 2 is coded but a different year;
        # 3 is blank in the PUR file; 4 carries a code we hold no row for.
        for use_no, year in ((1, 2023), (1, 2023), (2, 2023), (2, 2022), (3, 2023), (4, 2023), (5, 2023)):
            PesticideUse.objects.create(year=year, use_no=use_no, county=self.fresno, aerial_ground='F')
        self.pur = lookup_dir(PUR2023__txt=(
            PUR_HEADER
            + '2023,1,01,10,F,1107,N\n'
            + '2023,2,01,10,F,1290,N\n'
            + '2023,3,01,10,F,,N\n'
            + '2023,4,01,10,F,9999,N\n'
            + '2023,5,01,99,F,1107,N\n'
        ))

    def run_pass(self):
        return Command()._import_fume_codes(self.pur / 'PUR2023.txt', 2023, {10: self.fresno.pk})

    def test_sets_the_method_on_every_ingredient_row_of_the_record(self):
        self.run_pass()
        rows = PesticideUse.objects.filter(year=2023, use_no=1)
        assert rows.count() == 2
        assert {row.fume_method_id for row in rows} == {self.tarp.pk}
        assert PesticideUse.objects.get(year=2023, use_no=2).fume_method == self.other

    def test_only_touches_the_named_year(self):
        self.run_pass()
        assert PesticideUse.objects.get(year=2022, use_no=2).fume_method is None

    def test_skips_blanks_counts_unknown_codes_and_ignores_other_counties(self):
        coded, unknown = self.run_pass()
        assert PesticideUse.objects.get(year=2023, use_no=3).fume_method is None
        assert PesticideUse.objects.get(year=2023, use_no=4).fume_method is None
        # County 99 isn't one we import.
        assert PesticideUse.objects.get(year=2023, use_no=5).fume_method is None
        assert coded == 2
        assert unknown == {9999: 1}

    def test_is_idempotent_and_a_rerun_replaces_stale_codes(self):
        self.run_pass()
        PesticideUse.objects.filter(year=2023, use_no=3).update(fume_method=self.tarp)
        self.run_pass()
        assert PesticideUse.objects.filter(fume_method__isnull=False).count() == 3
        assert PesticideUse.objects.get(year=2023, use_no=3).fume_method is None


class FumeOnlyCommandTests(TestCase):
    def setUp(self):
        self.fresno = Region.objects.create(
            name='Fresno County', slug='fresno', type=Region.Type.COUNTY, external_id='06019')
        self.use = PesticideUse.objects.create(
            year=2023, use_no=7, county=self.fresno, aerial_ground='F', lbs_chemical=12.0)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zf:
            zf.writestr('pur2023/lookup_tables/FUMIGATION_METHODS.txt', METHODS)
            zf.writestr('pur2023/lookup_tables/COUNTY.txt', 'county_cd,county\n10,FRESNO\n')
            zf.writestr('pur2023/pur_data/PUR2023.txt', PUR_HEADER + '2023,7,01,10,F,1107,N\n')
        self.archive = buffer.getvalue()

    def download(self, year, tmp_dir):
        path = tmp_dir / f'pur{year}.zip'
        path.write_bytes(self.archive)
        return path

    def run_command(self, *args):
        with mock.patch.object(Command, '_download', self.download):
            call_command('import_pur', '--year', '2023', '--fume-only', *args, verbosity=0)

    def test_backfills_without_touching_the_records(self):
        self.run_command()
        self.use.refresh_from_db()
        assert self.use.fume_method.code == 1107
        assert (self.use.lbs_chemical, self.use.aerial_ground) == (12.0, 'F')
        # Nothing was reimported.
        assert PesticideUse.objects.count() == 1

    def test_is_idempotent(self):
        self.run_command()
        self.run_command()
        assert FumigationMethod.objects.count() == 2
        assert PesticideUse.objects.get().fume_method.code == 1107

    def test_skip_lookup_with_no_methods_loaded_changes_nothing(self):
        out = io.StringIO()
        with mock.patch.object(Command, '_download', self.download):
            call_command('import_pur', '--year', '2023', '--fume-only', '--skip-lookup', stdout=out)
        assert 'No fumigation methods loaded' in out.getvalue()

    def test_skip_lookup_uses_the_methods_already_loaded(self):
        FumigationMethod.objects.create(code=1107, name='Kept as is')
        self.run_command('--skip-lookup')
        assert FumigationMethod.objects.count() == 1
        assert PesticideUse.objects.get().fume_method.name == 'Kept as is'


class FumeEdgeTests(TestCase):
    def setUp(self):
        self.fresno = Region.objects.create(
            name='Fresno County', slug='fresno', type=Region.Type.COUNTY, external_id='06019')

    def test_an_older_file_cannot_reactivate_an_ended_code(self):
        Command()._import_fumigation_methods(lookup_dir(FUMIGATION_METHODS__txt=METHODS))
        old = METHODS.replace('1290,"1,3-Dichloropropene - Other label method [6448]",N', '1290,"1,3-Dichloropropene - Other label method [6448]",Y')
        Command()._import_fumigation_methods(lookup_dir(FUMIGATION_METHODS__txt=old))
        assert FumigationMethod.objects.get(code=1290).active is False

    def test_a_code_can_end(self):
        Command()._import_fumigation_methods(lookup_dir(FUMIGATION_METHODS__txt=METHODS.replace(',N,', ',Y,')))
        Command()._import_fumigation_methods(lookup_dir(FUMIGATION_METHODS__txt=METHODS))
        assert FumigationMethod.objects.get(code=1290).active is False

    def test_short_rows_are_reported(self):
        FumigationMethod.objects.create(code=1107, name='T')
        pur = lookup_dir(PUR2023__txt=PUR_HEADER + '2023,1,01,10,F,1107,N\n2023,2\n')
        command = Command()
        command.stdout = io.StringIO()
        command._import_fume_pass({'udc_dir': pur, 'lookup_dir': pur}, 2023)
        assert '1 short or malformed rows skipped' in command.stdout.getvalue()


class FullImportFumeTests(TestCase):
    def test_the_full_import_codes_the_records_it_just_loaded(self):
        fresno = Region.objects.create(
            name='Fresno County', slug='fresno', type=Region.Type.COUNTY, external_id='06019')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zf:
            zf.writestr('pur2023/lookup_tables/FUMIGATION_METHODS.txt', METHODS)
            zf.writestr('pur2023/lookup_tables/COUNTY.txt', 'county_cd,county\n10,FRESNO\n')
            zf.writestr('pur2023/pur_data/udc23_10.txt', 'use_no,aer_gnd_ind,lbs_chm_used\n7,F,12\n8,G,3\n')
            zf.writestr('pur2023/pur_data/PUR2023.txt', PUR_HEADER + '2023,7,01,10,F,1107,N\n2023,8,01,10,G,,N\n')

        def download(command, year, tmp_dir):
            path = tmp_dir / f'pur{year}.zip'
            path.write_bytes(buffer.getvalue())
            return path

        with mock.patch.object(Command, '_download', download):
            call_command('import_pur', '--year', '2023', verbosity=0)
        assert PesticideUse.objects.get(use_no=7).fume_method.code == 1107
        assert PesticideUse.objects.get(use_no=8).fume_method is None


class ByFumeMethodTests(TestCase):
    def setUp(self):
        self.fresno = Region.objects.create(
            name='Fresno County', slug='fresno', type=Region.Type.COUNTY, external_id='06019')
        self.tarp = FumigationMethod.objects.create(code=1107, name='Tarpaulin [6447]')
        self.drip = FumigationMethod.objects.create(code=1201, name='Drip [6448]')

    def use(self, use_no, lbs, method=None, year=2023):
        return PesticideUse.objects.create(
            year=year, use_no=use_no, county=self.fresno, aerial_ground='F',
            lbs_chemical=lbs, fume_method=method)

    def test_groups_by_method_biggest_first_with_not_recorded_last(self):
        self.use(1, 100, self.drip)
        self.use(2, 300, self.tarp)
        self.use(3, 900)
        self.use(4, 100, self.tarp)
        rows = stats.by_fume_method(PesticideUse.objects.all())
        assert [(r['method'], r['label'], r['lbs'], r['applications']) for r in rows] == [
            (self.tarp, 'Tarpaulin [6447]', 400, 2),
            (self.drip, 'Drip [6448]', 100, 1),
            (None, 'Not recorded', 900, 1),
        ]
        assert [round(r['share'], 4) for r in rows] == [0.2857, 0.0714, 0.6429]
        assert abs(sum(r['share'] for r in rows) - 1) < 1e-9
        assert abs(sum(r['app_share'] for r in rows) - 1) < 1e-9

    def test_applications_count_rows_within_one_chemical(self):
        # One record, three active ingredients: three rows. A chemical's own
        # page sees one of them, so it counts rows, as the rollup's
        # `applications` does.
        for _ in range(3):
            self.use(1, 10, self.tarp)
        rows = stats.by_fume_method(PesticideUse.objects.all(), chemical_scoped=True)
        assert rows[0]['applications'] == 3
        assert rows[0]['lbs'] == 30

    def test_applications_count_each_record_once_across_chemicals(self):
        # The same record on a product or commodity page: one application,
        # chemical pounds still summed over its ingredients, product pounds
        # (repeated on every row) counted once.
        for _ in range(3):
            PesticideUse.objects.create(
                year=2023, use_no=1, county=self.fresno, aerial_ground='F',
                lbs_chemical=10, lbs_product=100, fume_method=self.tarp)
        rows = stats.by_fume_method(PesticideUse.objects.all())
        assert rows[0]['applications'] == 1
        assert rows[0]['lbs'] == 30
        rows = stats.by_fume_method(PesticideUse.objects.all(), 'lbs_product', once=True)
        assert rows[0]['applications'] == 1
        assert rows[0]['lbs'] == 100

    def test_the_lbs_field_is_selectable(self):
        PesticideUse.objects.create(
            year=2023, use_no=1, county=self.fresno, aerial_ground='F',
            lbs_chemical=1, lbs_product=5, fume_method=self.tarp)
        assert stats.by_fume_method(PesticideUse.objects.all(), lbs_field='lbs_product')[0]['lbs'] == 5

    def test_empty_is_empty(self):
        assert stats.by_fume_method(PesticideUse.objects.none()) == []


class FumigantPageTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.tarp = FumigationMethod.objects.create(code=1107, name='Tarpaulin/Deep/Broadcast [6447.3(a)(5)]')
        self.drip = FumigationMethod.objects.create(code=1201, name='Drip [6448]')
        # Chemical 1 / product 1: uses 1 and 2 (Fresno, 2023) and 7 (2022, Fresno)
        # become field fumigations; use 3 (Kern) stays aerial.
        PesticideUse.objects.filter(pk=1).update(aerial_ground='F', fume_method=self.tarp)
        PesticideUse.objects.filter(pk=2).update(aerial_ground='F', fume_method=self.drip)
        PesticideUse.objects.filter(pk=7).update(aerial_ground='F')
        PesticideUse.objects.filter(pk=3).update(aerial_ground='F', fume_method=self.tarp)
        PesticideUse.objects.filter(pk=3).update(county_id=9002)
        self.chemical = Chemical.objects.get(pk=1)
        self.product = Product.objects.get(pk=1)

    def make_fumigant(self):
        Chemical.objects.filter(pk=1).update(categories=[Chemical.Category.FUMIGANT])
        Product.objects.filter(pk=1).update(is_fumigant=True)
        self.chemical.refresh_from_db()

    def get(self, obj, **params):
        params.setdefault('year', 2023)
        return self.client.get(obj.get_absolute_url(), params)

    def test_a_fumigant_chemical_shows_the_breakdown(self):
        self.make_fumigant()
        response = self.get(self.chemical)
        rows = response.context['by_fume_method']
        assert [(r['label'], r['lbs'], r['applications']) for r in rows] == [
            ('Tarpaulin/Deep/Broadcast [6447.3(a)(5)]', 130, 2),
            ('Drip [6448]', 50, 1),
        ]
        html = response.content.decode()
        assert 'How it was fumigated' in html
        assert html.index('How it was applied') < html.index('How it was fumigated')
        assert 'Tarpaulin/Deep/Broadcast [6447.3(a)(5)]' in html

    def test_a_fumigant_product_shows_it_on_product_pounds(self):
        self.make_fumigant()
        rows = self.get(self.product).context['by_fume_method']
        assert [(r['lbs'], r['applications']) for r in rows] == [(325, 2), (125, 1)]

    def test_a_non_fumigant_page_has_no_block(self):
        response = self.get(self.chemical)
        assert response.context['by_fume_method'] == []
        assert 'How it was fumigated' not in response.content.decode()

    def test_hidden_when_no_field_fumigation_is_in_scope(self):
        self.make_fumigant()
        response = self.get(self.chemical, year=2022, county='kern')
        assert not response.context['by_fume_method']
        assert 'How it was fumigated' not in response.content.decode()

    def test_county_scope_is_respected(self):
        self.make_fumigant()
        rows = self.get(self.chemical, county='kern').context['by_fume_method']
        assert [(r['label'], r['applications']) for r in rows] == [('Tarpaulin/Deep/Broadcast [6447.3(a)(5)]', 1)]

    def test_records_without_a_code_are_one_not_recorded_row(self):
        self.make_fumigant()
        rows = self.get(self.chemical, year=2022).context['by_fume_method']
        assert [(r['label'], r['lbs']) for r in rows] == [('Not recorded', 80)]

    def test_all_years_sums_every_year(self):
        self.make_fumigant()
        rows = self.get(self.chemical, year='all').context['by_fume_method']
        assert [(r['label'], r['lbs']) for r in rows] == [
            ('Tarpaulin/Deep/Broadcast [6447.3(a)(5)]', 130), ('Drip [6448]', 50), ('Not recorded', 80)]

    def test_all_years_is_cached(self):
        self.make_fumigant()
        self.get(self.chemical, year='all')
        PesticideUse.objects.all().update(fume_method=None)
        rows = self.get(self.chemical, year='all').context['by_fume_method']
        assert rows[0]['label'] == 'Tarpaulin/Deep/Broadcast [6447.3(a)(5)]'
        cache.clear()
        assert [r['label'] for r in self.get(self.chemical, year='all').context['by_fume_method']] == ['Not recorded']

    def test_the_narrowing_is_respected(self):
        self.make_fumigant()
        # Field fumigation and "aerial" can't overlap.
        assert not self.get(self.chemical, narrow='aerial').context['by_fume_method']
        rows = self.get(self.chemical, narrow='fumigant').context['by_fume_method']
        assert sum(r['applications'] for r in rows) == 3

    def test_pounds_are_hidden_for_a_placeholder(self):
        self.make_fumigant()
        Chemical.objects.filter(pk=1).update(chem_code=-1)
        html = self.get(Chemical.objects.get(pk=1)).content.decode()
        block = html[html.index('How it was fumigated'):]
        assert 'Share of applications' in block.split('</table>')[0]


class RecordsBrowserFumeTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.tarp = FumigationMethod.objects.create(code=1107, name='Tarpaulin/Deep/Broadcast [6447.3(a)(5)]')
        self.drip = FumigationMethod.objects.create(code=1201, name='Drip [6448]')
        self.unused = FumigationMethod.objects.create(code=1300, name='Unused [6449]')
        PesticideUse.objects.filter(pk=1).update(aerial_ground='F', fume_method=self.tarp)
        PesticideUse.objects.filter(pk=2).update(aerial_ground='F', fume_method=self.drip)
        self.url = reverse('pesticides:records')

    def pks(self, response):
        return sorted(u.pk for u in response.context['object_list'])

    def test_filters_by_method_code(self):
        assert self.pks(self.client.get(self.url, {'fume_method': 1107})) == [1]
        assert self.pks(self.client.get(self.url, {'fume_method': 1201})) == [2]

    def test_a_code_that_is_not_offered_is_an_invalid_choice_and_ignored(self):
        response = self.client.get(self.url, {'fume_method': 1300})
        assert response.context['form'].errors['fume_method']
        assert self.pks(response) == [1, 2, 3, 4, 5, 6]

    def test_blank_is_no_filter(self):
        assert self.pks(self.client.get(self.url)) == [1, 2, 3, 4, 5, 6]

    def test_the_select_offers_only_methods_in_use(self):
        form = self.client.get(self.url).context['form']
        assert [value for value, _ in form.fields['fume_method'].choices] == ['', '1201', '1107']

    def test_totals_are_cached_per_filter(self):
        assert self.client.get(self.url, {'fume_method': 1107}).context['totals']['applications'] == 1
        assert self.client.get(self.url, {'fume_method': 1201}).context['totals']['applications'] == 1
        assert self.client.get(self.url).context['totals']['applications'] == 6

    def test_the_method_cell_names_the_technique(self):
        html = self.client.get(self.url, {'fume_method': 1107}).content.decode()
        assert 'Field fumigation — Tarpaulin/Deep/Broadcast' in html
        assert 'title="Tarpaulin/Deep/Broadcast [6447.3(a)(5)]"' in html

    def test_a_field_fumigation_without_a_code_is_plain(self):
        PesticideUse.objects.filter(pk=3).update(aerial_ground='F')
        html = self.client.get(self.url).content.decode()
        assert 'Field fumigation</td>' in html


class FumeApiTests(TestCase):
    def setUp(self):
        self.fresno = Region.objects.create(
            name='Fresno County', slug='fresno', type=Region.Type.COUNTY, external_id='06019',
            metadata={'ca_county_code': '10'})
        self.tarp = FumigationMethod.objects.create(code=1107, name='Tarpaulin [6447]')
        self.coded = PesticideUse.objects.create(
            year=2023, use_no=1, county=self.fresno, aerial_ground='F', fume_method=self.tarp)
        self.plain = PesticideUse.objects.create(year=2023, use_no=2, county=self.fresno, aerial_ground='G')
        self.url = reverse('api:v2:pesticides:use-list')

    def test_the_serializer_carries_the_method_or_null(self):
        rows = {r['use_no']: r for r in self.client.get(self.url).json()['data']}
        assert rows[1]['fume_method'] == {'id': self.tarp.sqid, 'code': 1107, 'name': 'Tarpaulin [6447]'}
        assert rows[2]['fume_method'] is None

    def test_filter_by_code(self):
        data = self.client.get(self.url, {'fume_method': 1107}).json()
        assert [r['use_no'] for r in data['data']] == [1]
