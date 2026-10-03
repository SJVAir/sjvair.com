"""
contable-sample.pdf is pages 1-3, 9, 11 and 12 of the real table dated
2024-12-17:  qpdf contable.pdf --pages . 1-3,9,11,12 -- contable-sample.pdf
"""
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from camp.apps.emissions import stats
from camp.apps.emissions.importers import contable
from camp.apps.emissions.models import SourceImport, ToxicPollutant

SAMPLE = Path(__file__).parent / 'data' / 'contable-sample.pdf'


class ParserTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rows, cls.date = contable.parse(SAMPLE)
        cls.by_id = {row['carb_id']: row for row in cls.rows}

    def test_date_and_row_shape(self):
        assert self.date == date(2024, 12, 17)
        assert len(self.rows) > 60
        assert set(self.rows[0]) == {'carb_id', 'cas_number', 'name', 'acute_rel', 'chronic_rel', 'iur', 'mwaf'}

    def test_cas_row_with_tac_suffixes(self):
        benzene = self.by_id['71432']
        assert benzene['name'] == 'Benzene' and benzene['cas_number'] == '71-43-2'
        assert (benzene['acute_rel'], benzene['chronic_rel'], benzene['iur'], benzene['mwaf']) == (27.0, 3.0, 2.9e-5, 1.0)

    def test_carb_code_rows(self):
        diesel = self.by_id['9901']
        assert diesel['cas_number'] == '' and diesel['iur'] == 3.0e-4 and diesel['chronic_rel'] == 5.0 and diesel['acute_rel'] is None
        assert self.by_id['1020']['iur'] == 0.14

    def test_several_ids_share_a_row(self):
        assert self.by_id['7440382']['iur'] == self.by_id['1016']['iur'] == self.by_id['1015']['iur'] == 3.3e-3
        assert self.by_id['1150']['iur'] == self.by_id['1151']['iur'] == 1.1e-3

    def test_blanks_mwaf_and_footnotes(self):
        assert self.by_id['7664417']['iur'] is None and self.by_id['7664417']['chronic_rel'] == 200.0
        assert self.by_id['7789062']['mwaf'] == 0.2554
        assert self.by_id['7440484']['iur'] == 7.7e-3
        assert self.by_id['50328']['name'] == 'Benzo(a)pyrene'

    def test_helpers(self):
        assert contable.ids('7440-38-2\n1016\n[1015]') == ['7440382', '1016', '1015']
        assert contable.ids('Substance') == []
        assert contable.number('1.5E-01\nTAC') == 0.15 and contable.number('') is None
        assert contable.clean_name('PARTICULATE EMISSIONS FROM\nDIESEL-FUELED ENGINESTAC, i') == 'Particulate emissions from diesel-fueled engines'
        assert contable.clean_name('CHROMIUM 6+TAC values also apply to:g') == 'Chromium 6+'
        assert contable.clean_name('Fluorides and compounds') == 'Fluorides and compounds'


class ApplyTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_import_upserts_weights_names_and_the_stamp(self):
        ToxicPollutant.objects.filter(carb_id='71432').update(iur=1.0, cancer_weight=99, name='Old benzene')
        call_command('import_health_values', path=str(SAMPLE))
        benzene = ToxicPollutant.objects.get(carb_id='71432')
        assert benzene.name == 'Benzene' and benzene.slug == 'benzene'
        assert abs(benzene.cancer_weight - 2.9e-5 * 7700) < 1e-9
        assert benzene.health_values_date == date(2024, 12, 17)
        diesel = ToxicPollutant.objects.get(carb_id='9901')
        assert diesel.name == 'Diesel PM' and diesel.slug == 'diesel-pm' and abs(diesel.cancer_weight - 2.31) < 1e-9
        assert ToxicPollutant.objects.get(carb_id='1150').weighted is False
        assert ToxicPollutant.objects.get(carb_id='1150').cancer_weight == 0
        assert ToxicPollutant.objects.get(carb_id='1151').cancer_weight > 0
        assert ToxicPollutant.objects.get(carb_id='7664417').kind == 'precursor'
        assert ToxicPollutant.objects.get(carb_id='7664417').chronic_weight == 0
        stamp = SourceImport.latest('contable')
        assert stamp.version == '2024-12-17' and stamp.data_through == date(2024, 12, 17)

    def test_rerun_is_idempotent_and_keeps_slugs(self):
        call_command('import_health_values', path=str(SAMPLE))
        count = ToxicPollutant.objects.count()
        ToxicPollutant.objects.filter(carb_id='9901').update(slug='old-slug')
        call_command('import_health_values', path=str(SAMPLE))
        assert ToxicPollutant.objects.count() == count
        assert ToxicPollutant.objects.get(carb_id='9901').slug == 'old-slug'

    def test_import_bumps_the_cache_generation(self):
        before = stats.generation()
        call_command('import_health_values', path=str(SAMPLE))
        assert stats.generation() == before + 1
