from django.contrib.gis.geos import Point
from django.test import TestCase

from camp.apps.regions.models import Location, Region


class LocationSearchTests(TestCase):
    """Location.objects.search(q): name matching, typo tolerance, town matching and ordering."""

    fixtures = ['regions.yaml']

    def make(self, name, city_name, type=Location.Type.PUBLIC_SCHOOL, source='cde-public', external_id=None, point=None, city=None, **kw):
        # Rows ~1.1 km apart unless a point is given, so one_per_place() keeps them separate.
        self.n += 1
        return Location.objects.create(
            name=name, city_name=city_name, type=type, source=source,
            external_id=external_id or str(self.n).zfill(9),
            point=point or Point(-119.0, 36.0 + self.n * 0.01, srid=4326),
            city=city, **kw,
        )

    def setUp(self):
        self.n = 0
        self.fresno = Region.objects.get(type=Region.Type.CITY, name='Fresno')
        self.visalia_lincoln = self.make('Lincoln Elementary', 'Visalia')
        self.make('Lincoln Elementary', 'Fresno', city=self.fresno)
        self.make('Lincoln Elementary', 'Bakersfield')
        self.make('Lincoln Elementary', 'dinuba')
        # A mailing city (Stockton) that isn't its linked CDP's name (Lincoln Village),
        # and the CDP's name starts with a word of the school's name.
        lincoln_village = Region.objects.create(name='Lincoln Village', slug='lincoln-village', type=Region.Type.CDP, external_id='0641712')
        self.make('Lincoln Elementary', 'Stockton', city=lincoln_village)
        self.make('Lincoln Elementary', 'Madera')  # sorts between "lincoln village" and "stockton"
        self.make('Abraham Lincoln Jr. High', 'Bakersfield')
        self.make('Roosevelt Elementary', 'Fresno', city=self.fresno)
        self.make('Fresno High', 'Fresno', city=self.fresno)
        self.make('Bullard High', 'Fresno', city=self.fresno)
        self.make('FRESNO EOC HEAD START', 'CARUTHERS', type=Location.Type.CHILD_CARE, source='cdss-ccl')

    def search(self, q):
        return [(l.name, l.city_name) for l in Location.objects.search(q)]

    def test_prefix_beats_word_start_beats_substring(self):
        names = [name for name, city in self.search('linc')]
        assert names[:7] == ['Lincoln Elementary'] * 6 + ['Abraham Lincoln Jr. High']

    def test_same_name_orders_by_city_ignoring_case(self):
        rows = self.search('lincoln elementary')
        # The Stockton row sorts as the Stockton it shows, not as its linked CDP (Lincoln
        # Village, before Madera). Its CDP matching "lincoln" doesn't lift it above the
        # others: they all start with q.
        assert [city for name, city in rows[:6]] == ['Bakersfield', 'dinuba', 'Fresno', 'Madera', 'Stockton', 'Visalia']

    def test_typo_matches(self):
        rows = self.search('Linclon')
        lincolns = [row for row in rows if 'Lincoln' in row[0]]
        assert len(lincolns) == 7
        assert self.search('Rosevelt')[0] == ('Roosevelt Elementary', 'Fresno')

    def test_town_suffix_ranks_first(self):
        assert self.search('lincoln visalia')[0] == ('Lincoln Elementary', 'Visalia')
        # Only the Visalia row matched the town, including among rows with no linked city.
        town_matched = [(l.name, l.city_name) for l in Location.objects.search('lincoln visalia') if 2 <= l.search_rank <= 4]
        assert town_matched == [('Lincoln Elementary', 'Visalia')]

    def test_town_prefix_ranks_first(self):
        assert self.search('visalia lincoln')[0] == ('Lincoln Elementary', 'Visalia')

    def test_partial_town(self):
        assert self.search('lincoln vis')[0] == ('Lincoln Elementary', 'Visalia')

    def test_town_alone_does_not_match(self):
        assert ('Lincoln Elementary', 'Visalia') not in self.search('roosevelt visalia')

    def test_single_word_never_splits(self):
        assert self.search('visalia') == []

    def test_town_word_still_matches_names(self):
        # Bullard High matches as name "high" in town "fresno", below a name starting with q.
        assert self.search('fresno high')[:2] == [('Fresno High', 'Fresno'), ('Bullard High', 'Fresno')]
        assert ('FRESNO EOC HEAD START', 'CARUTHERS') in self.search('fresno')

    def test_town_matches_the_city_name_or_the_linked_city(self):
        self.make('Jefferson Elementary', 'Calwa', city=self.fresno)

        for q in ['jefferson fresno', 'jefferson calwa']:
            row = Location.objects.search(q).first()
            assert row.name == 'Jefferson Elementary'
            assert row.search_rank == 4  # town matched, name part a prefix

    def test_town_matches_a_mailing_city_unlike_the_linked_one(self):
        stockton = ('Lincoln Elementary', 'Stockton')
        # The row's own city_name is a town...
        assert self.search('lincoln stockton')[0] == stockton
        # ...and so is its linked CDP's name.
        assert self.search('lincoln elementary lincoln village')[0] == stockton
        # Two words that are the CDP's name read best as a name; the row is still found.
        assert stockton in self.search('lincoln village')

    def test_retired_excluded(self):
        self.visalia_lincoln.retire(self.visalia_lincoln.created.date())
        assert ('Lincoln Elementary', 'Visalia') not in self.search('lincoln')

    def test_child_care_licenses_are_one_row(self):
        point = Point(-119.5, 36.5, srid=4326)
        self.make('Little Acorns', 'Hanford', type=Location.Type.CHILD_CARE, source='cdss-ccl', external_id='153400002', point=point)
        self.make('LITTLE ACORNS', 'Hanford', type=Location.Type.CHILD_CARE, source='cdss-ccl', external_id='153400001',
            point=Point(-119.5, 36.50045, srid=4326))  # ~50 m north

        rows = list(Location.objects.search('little acorns'))

        assert [row.external_id for row in rows] == ['153400001']
        assert rows[0].licenses == 2

    def test_wildcards_match_literally(self):
        self.make('100% Kids Club', 'Tulare')
        self.make('1000 Oaks Preschool', 'Tulare')
        self.make('Kids_Club', 'Tulare')
        self.make('KidsZClub', 'Tulare')

        percent = list(Location.objects.search('100%'))
        assert percent[0].name == '100% Kids Club'
        assert percent[0].search_rank == 6
        assert all(row.search_rank < 6 for row in percent if row.name == '1000 Oaks Preschool')

        # `_` is a literal underscore, not "any one character": only Kids_Club
        # contains "s_c". KidsZClub could only come in on similarity.
        underscore = {row.name: row for row in Location.objects.search('s_c')}
        assert underscore['Kids_Club'].search_rank == 1
        assert 'KidsZClub' not in underscore or underscore['KidsZClub'].search_similarity >= 0.3

        # A backslash is literal too: as LIKE's escape character, 'a\\b' would be
        # a prefix of "Abraham Lincoln Jr. High".
        self.make('A\\B Academy', 'Tulare')
        prefixed = [row.name for row in Location.objects.search('a\\b') if row.search_rank == 6]
        assert prefixed == ['A\\B Academy']

    def test_extra_spaces_are_ignored(self):
        assert self.search('  lincoln   visalia ') == self.search('lincoln visalia')

    def test_location_without_city(self):
        self.make('Lincoln Annex', '')
        assert ('Lincoln Annex', '') in self.search('lincoln')

    def test_blank_query_returns_nothing(self):
        assert self.search('   ') == []

    def test_it_stays_filterable_and_sliceable(self):
        rows = list(Location.objects.search('lincoln').filter(city_name='Bakersfield').select_related('city', 'county')[:1])
        assert [(row.name, row.city_name) for row in rows] == [('Lincoln Elementary', 'Bakersfield')]
        # search_rank and search_similarity survive the chain (they're set as rows are read).
        assert rows[0].search_rank == 6
        assert rows[0].search_similarity == 1.0
