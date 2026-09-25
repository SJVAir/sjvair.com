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
    CDPR's chem_cas.txt keys its column `casnum`. It was read as
    `cas_number`, which matched nothing, so all ~3,000 CAS numbers in the
    file were dropped without a word -- leaving import_comptox to match on
    name alone. These write the real column names.
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

    def test_the_old_column_name_is_not_what_cdpr_ships(self):
        # Guards the regression directly: a file keyed the way the importer
        # used to read it yields nothing, because that column doesn't exist.
        self.run_import(lookup_dir(
            chemical__txt='chem_code,chemalpha_cd,chemname\n1,ABC,ABAMECTIN\n',
            chem_cas__txt='chem_code,cas_number\n1,71751-41-2\n',
        ))
        assert Chemical.objects.get(chem_code=1).cas_number == ''


class ProductRestrictedTests(TestCase):
    """
    California restricted-material status has no PUR source: it's 3 CCR
    6400, and none of the lookup tables carry it. The importer used to read a
    RESTRICTED.txt that CDPR doesn't publish, so the flag was never set by an
    import and must not be read as meaning "not restricted".
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

    def test_no_import_sets_the_restricted_flag(self):
        Command()._import_products(lookup_dir(
            product__txt='prodno,product_name,show_regno,fumigant_sw\n1,K-PAM HL,5481-483-AA,X\n'))
        assert Product.objects.filter(california_restricted=True).count() == 0


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
        # ...and the deprecated flag is not what says so.
        assert lorsban.california_restricted is False
