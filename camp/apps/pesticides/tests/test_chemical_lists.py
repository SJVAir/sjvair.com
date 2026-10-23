import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from camp.apps.pesticides.forms import ChemicalFilterForm
from camp.apps.pesticides.management.commands.import_comptox import Command as ComptoxCommand
from camp.apps.pesticides.models import Chemical

TAC = Chemical.Category.TOXIC_AIR_CONTAMINANT
CARCINOGEN = Chemical.Category.CARCINOGEN
FUMIGANT = Chemical.Category.FUMIGANT

PROP65_CSV = '''"Proposition 65 list preamble"
Chemical,Type of Toxicity,Listing Mechanism,CAS No.,Date Listed
Benzene,"cancer, developmental, male",SQE,71-43-2,27-Feb-87
Chromium (hexavalent compounds),cancer,LC,---,27-Feb-87
Nickel hydroxide,cancer,LC,12054-48-7; 12125-56-3,1-Oct-89
'''


def chemical(code, name, cas='', categories=()):
    return Chemical.objects.create(chem_code=code, name=name, cas_number=cas, categories=list(categories))


def run(command, *args, **options):
    out = StringIO()
    call_command(command, *args, stdout=out, **options)
    return out.getvalue()


class CarbTacTests(TestCase):
    """import_carbtac: CARB's TAC list (17 CCR 93000/93001), not every substance in its health-values table."""

    def tagged(self):
        return {c.name: TAC in c.categories for c in Chemical.objects.all()}

    def test_the_list_decides_the_tag(self):
        chemical(1, '1,3-DICHLOROPROPENE', '542-75-6')
        chemical(2, '2,4-D, DIMETHYLAMINE SALT', '2008-39-1')  # a salt of a "salts and esters" listing
        chemical(3, 'MANCOZEB', '8018-01-7')                   # a manganese compound by structure, not by name
        chemical(4, '2-BUTOXYETHANOL', '111-76-2')             # a glycol ether
        chemical(5, 'ALPHA-BHC', '319-84-6')                   # lindane, all isomers
        chemical(6, 'AMMONIA', '7664-41-7', [TAC])             # in CARB's health-values table, not a TAC
        chemical(7, 'CHROMOBACTERIUM SUBTSUGAE STRAIN PRAA4-1')
        chemical(8, 'TRICLOPYR, BUTOXYETHYL ESTER', '64700-56-7')
        run('import_carbtac')
        assert self.tagged() == {
            '1,3-DICHLOROPROPENE': True, '2,4-D, DIMETHYLAMINE SALT': True, 'MANCOZEB': True,
            '2-BUTOXYETHANOL': True, 'ALPHA-BHC': True, 'AMMONIA': False,
            'CHROMOBACTERIUM SUBTSUGAE STRAIN PRAA4-1': False, 'TRICLOPYR, BUTOXYETHYL ESTER': False,
        }

    def test_it_leaves_the_other_categories_alone(self):
        # The cancer potencies in CARB's table aren't Prop 65 listings: only import_prop65 sets CARCINOGEN.
        chloropicrin = chemical(1, 'CHLOROPICRIN', '76-06-2', [FUMIGANT, TAC])
        benzene = chemical(2, 'BENZENE', '71-43-2', [CARCINOGEN])
        run('import_carbtac')
        chloropicrin.refresh_from_db()
        benzene.refresh_from_db()
        assert chloropicrin.categories == [FUMIGANT]
        assert benzene.categories == sorted([CARCINOGEN, TAC])

    def test_a_dry_run_writes_nothing(self):
        chemical(1, 'AMMONIA', '7664-41-7', [TAC])
        out = run('import_carbtac', dry_run=True)
        assert 'Removed TOXIC_AIR_CONTAMINANT: 1' in out and 'Dry run' in out
        assert Chemical.objects.get().categories == [TAC]


class Prop65Tests(TestCase):
    """import_prop65 alone sets the Prop 65 categories, group listings included."""

    def run_csv(self, **options):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'p65.csv'
            path.write_text(PROP65_CSV, encoding='latin-1')
            return run('import_prop65', path=str(path), **options)

    def test_cas_and_group_listings(self):
        benzene = chemical(1, 'BENZENE', '71-43-2', [TAC])
        dichromate = chemical(2, 'SODIUM DICHROMATE', '10588-01-9')  # no CAS of its own on the list
        nickel = chemical(3, 'NICKEL HYDROXIDE', '12125-56-3')      # the second CAS in its cell
        self.run_csv()
        for obj in (benzene, dichromate, nickel):
            obj.refresh_from_db()
        assert benzene.categories == sorted([
            CARCINOGEN, Chemical.Category.DEVELOPMENTAL_TOXIN, Chemical.Category.REPRODUCTIVE_TOXIN, TAC,
        ])
        assert dichromate.categories == [CARCINOGEN]
        assert nickel.categories == [CARCINOGEN]

    def test_a_chemical_it_does_not_list_loses_the_prop65_categories(self):
        ammonia = chemical(1, 'AMMONIA', '7664-41-7', [CARCINOGEN, FUMIGANT])
        out = self.run_csv()
        ammonia.refresh_from_db()
        assert ammonia.categories == [FUMIGANT]
        assert 'cleared Prop 65 categories from 1' in out


class CategoryFilterTests(TestCase):
    def test_the_filter_offers_only_categories_an_import_assigns(self):
        offered = {value for value, label in ChemicalFilterForm().fields['category'].choices}
        assert Chemical.Category.OIL not in offered and Chemical.Category.BIOPESTICIDE not in offered
        assert {TAC, CARCINOGEN, FUMIGANT} <= offered


class HazardRefreshTests(TestCase):
    """import_comptox --phase hazard --refresh: an IARC reclassification reaches a chemical that already has a group."""

    def hazard(self, groups, **options):
        command = ComptoxCommand(stdout=StringIO())
        command.workers = 1
        with mock.patch.object(ComptoxCommand, '_get_iarc_group', side_effect=lambda dtxsid: groups[dtxsid]):
            command._phase_hazard(**options)

    def test_refresh_rechecks_classified_chemicals(self):
        glyphosate = chemical(1, 'GLYPHOSATE', '1071-83-6')
        Chemical.objects.filter(pk=glyphosate.pk).update(dtxsid='DTXSID1', iarc_group='2B')
        self.hazard({'DTXSID1': '2A'})
        glyphosate.refresh_from_db()
        assert glyphosate.iarc_group == '2B'  # without --refresh it's left alone
        self.hazard({'DTXSID1': '2A'}, refresh=True)
        glyphosate.refresh_from_db()
        assert glyphosate.iarc_group == '2A'

    def test_a_blank_answer_never_clears_a_group(self):
        captan = chemical(1, 'CAPTAN', '133-06-2')
        Chemical.objects.filter(pk=captan.pk).update(dtxsid='DTXSID2', iarc_group='3')
        self.hazard({'DTXSID2': ''}, refresh=True)
        captan.refresh_from_db()
        assert captan.iarc_group == '3'
