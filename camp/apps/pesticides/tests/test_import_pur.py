import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from camp.apps.pesticides.management.commands.import_pur import Command
from camp.apps.pesticides.models import Chemical, Product


def lookup_dir(**files):
    """A temporary PUR lookup directory holding the given files."""
    directory = Path(tempfile.mkdtemp())
    for name, text in files.items():
        (directory / name.replace('__', '.')).write_text(text)
    return directory


class ChemicalCasImportTests(TestCase):
    """
    CDPR's CAS lookup has changed its column name: chem_cas.txt through 2022
    keys it `casnum`, 2023's lookup_tables/CHEM_CAS.txt `cas_number`. Reading
    only one silently dropped every CAS number in the other year's file, and
    the empty value then wiped the CAS numbers already stored. These write
    the real column names of both.
    """

    def run_import(self, directory):
        Command()._import_chemicals(directory)

    def test_cas_numbers_come_off_the_casnum_column(self):
        self.run_import(lookup_dir(
            chemical__txt='chem_code,chemalpha_cd,chemname\n1,ABC,ABAMECTIN\n2,DEF,ACEPHATE\n',
            chem_cas__txt='chem_code,casnum\n1,71751-41-2\n2,30560-19-1\n',
        ))
        assert Chemical.objects.get(chem_code=1).cas_number == '71751-41-2'
        assert Chemical.objects.get(chem_code=2).cas_number == '30560-19-1'

    def test_a_chemical_with_no_cas_row_keeps_an_empty_one(self):
        self.run_import(lookup_dir(
            chemical__txt='chem_code,chemalpha_cd,chemname\n1,ABC,ABAMECTIN\n2,DEF,ACEPHATE\n',
            chem_cas__txt='chem_code,casnum\n1,71751-41-2\n',
        ))
        assert Chemical.objects.get(chem_code=2).cas_number == ''

    def test_no_cas_file_at_all(self):
        self.run_import(lookup_dir(
            chemical__txt='chem_code,chemalpha_cd,chemname\n1,ABC,ABAMECTIN\n'))
        assert Chemical.objects.get(chem_code=1).cas_number == ''

    def test_cas_numbers_come_off_the_2023_cas_number_column(self):
        # 2023's archive: upper-case files under lookup_tables/, and the CAS
        # column renamed.
        self.run_import(lookup_dir(
            CHEMICAL__txt='chem_code,chemname,general_ai_name\n1,ABAMECTIN,ABAMECTIN\n',
            CHEM_CAS__txt='chem_code,cas_number\n1,71751-41-2\n',
        ))
        assert Chemical.objects.get(chem_code=1).cas_number == '71751-41-2'

    def test_a_missing_cas_never_wipes_a_stored_one(self):
        Chemical.objects.create(chem_code=1, name='ABAMECTIN', cas_number='71751-41-2')
        # A later year with no CAS row for it, or no CAS file at all.
        self.run_import(lookup_dir(
            chemical__txt='chem_code,chemalpha_cd,chemname\n1,ABC,ABAMECTIN\n',
            chem_cas__txt='chem_code,casnum\n',
        ))
        assert Chemical.objects.get(chem_code=1).cas_number == '71751-41-2'
        self.run_import(lookup_dir(
            chemical__txt='chem_code,chemalpha_cd,chemname\n1,ABC,ABAMECTIN\n'))
        assert Chemical.objects.get(chem_code=1).cas_number == '71751-41-2'

    def test_2022_then_2023_keeps_every_cas_number(self):
        # The reported regression: 2022 filled CAS numbers, then 2023's
        # renamed column read as empty and blanked them.
        self.run_import(lookup_dir(
            chemical__txt='chem_code,chemalpha_cd,chemname\n1,ABC,ABAMECTIN\n2,DEF,ACEPHATE\n',
            chem_cas__txt='chem_code,casnum\n1,71751-41-2\n2,30560-19-1\n',
        ))
        self.run_import(lookup_dir(
            CHEMICAL__txt='chem_code,chemname,general_ai_name\n1,ABAMECTIN,ABAMECTIN\n2,ACEPHATE,ACEPHATE\n',
            CHEM_CAS__txt='chem_code,cas_number\n2,30560-19-1\n',
        ))
        assert Chemical.objects.get(chem_code=1).cas_number == '71751-41-2'
        assert Chemical.objects.get(chem_code=2).cas_number == '30560-19-1'


class ProductRestrictedTests(TestCase):
    """
    CDPR's 2023+ archives carry lookup_tables/RESTRICTED.txt, one row per
    product with `x` or blank in federally_restricted / california_restricted.
    Earlier archives have no such file. A product the file doesn't list stays
    NULL, which the ingredient rule in `is_restricted` then covers.
    """

    def test_products_import_and_fumigant_comes_off_fumigant_sw(self):
        Command()._import_products(lookup_dir(
            product__txt=(
                'prodno,product_name,show_regno,fumigant_sw\n'
                '1,K-PAM HL,5481-483-AA,X\n'
                '2,SOME HERBICIDE,123-456,\n'
            )))
        assert Product.objects.get(prodno=1).fumigant is True
        assert Product.objects.get(prodno=2).fumigant is False

    def products(self):
        Command()._import_products(lookup_dir(
            product__txt=(
                'prodno,product_name,show_regno,fumigant_sw\n'
                '325,PRODUCT A,1-1,\n'
                '1309,PRODUCT B,2-2,\n'
                '77,PRODUCT C,3-3,\n'
                '88,PRODUCT D,4-4,\n'
            )))

    def test_the_product_import_leaves_the_flags_null(self):
        self.products()
        product = Product.objects.get(prodno=325)
        assert product.california_restricted is None
        assert product.federally_restricted is None

    def test_restricted_file_sets_both_flags(self):
        self.products()
        Command()._import_restricted(lookup_dir(
            RESTRICTED__txt=(
                'prodno,federally_restricted,california_restricted\n'
                '325,x,\n'
                '1309,x,x\n'
                '77,,\n'
                '999999,x,x\n'
            )))
        a = Product.objects.get(prodno=325)
        assert a.federally_restricted is True
        assert a.california_restricted is False
        b = Product.objects.get(prodno=1309)
        assert b.federally_restricted is True
        assert b.california_restricted is True
        c = Product.objects.get(prodno=77)
        assert c.federally_restricted is False
        assert c.california_restricted is False

    def test_a_product_absent_from_the_file_stays_null(self):
        self.products()
        Command()._import_restricted(lookup_dir(
            RESTRICTED__txt='prodno,federally_restricted,california_restricted\n325,x,x\n'))
        d = Product.objects.get(prodno=88)
        assert d.federally_restricted is None
        assert d.california_restricted is None

    def test_an_import_without_the_file_leaves_flags_unchanged(self):
        self.products()
        Command()._import_restricted(lookup_dir(
            RESTRICTED__txt='prodno,federally_restricted,california_restricted\n325,x,x\n'))
        Command()._import_restricted(lookup_dir())
        a = Product.objects.get(prodno=325)
        assert a.federally_restricted is True
        assert a.california_restricted is True
        assert Product.objects.get(prodno=88).california_restricted is None


class RestrictedMaterialsImportTests(TestCase):
    """
    3 CCR 6400 names active ingredients, so the classification lands on
    Chemical.categories and a product is restricted when one of its
    ingredients is.
    """

    fixtures = ['pesticides-explorer']

    def test_the_datafile_names_only_chemicals_that_exist(self):
        # A name that matches nothing means the file and CDPR's chemical
        # table have drifted. Silence there is how the old RESTRICTED.txt
        # lookup went unnoticed, so the command reports it -- this checks
        # the shipped file against the shipped chemical names.
        import yaml
        from pathlib import Path

        from django.conf import settings

        data = yaml.safe_load((Path(settings.BASE_DIR) / 'datafiles' / 'restricted-materials.yaml').read_text())
        assert data['entries']
        for entry in data['entries']:
            assert entry.get('regulation')
            assert entry.get('chemicals'), entry['regulation']
            for name in entry['chemicals']:
                assert name == name.upper(), name

    def test_import_classifies_by_name(self):
        Chemical.objects.filter(pk=2).update(categories=[])
        call_command('import_restricted_materials', verbosity=0)
        chlorpyrifos = Chemical.objects.get(pk=2)
        assert Chemical.Category.CALIFORNIA_RESTRICTED in chlorpyrifos.categories

    def test_import_is_idempotent(self):
        call_command('import_restricted_materials', verbosity=0)
        before = list(Chemical.objects.get(pk=2).categories)
        call_command('import_restricted_materials', verbosity=0)
        assert Chemical.objects.get(pk=2).categories == before

    def test_dry_run_writes_nothing(self):
        Chemical.objects.filter(pk=2).update(categories=[])
        call_command('import_restricted_materials', '--dry-run', verbosity=0)
        assert Chemical.objects.get(pk=2).categories == []

    def test_a_product_is_restricted_through_its_ingredients(self):
        call_command('import_restricted_materials', verbosity=0)
        lorsban = Product.objects.get(prodno=2)
        assert lorsban.is_restricted is True
        # ...and a product whose ingredients aren't restricted isn't.
        assert Product.objects.get(prodno=1).is_restricted is False
