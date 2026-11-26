from django.test import TestCase

from camp.apps.pesticides import notes
from camp.apps.pesticides.badges import BADGES, chemical_badges
from camp.apps.pesticides.models import Chemical


class BadgesTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_glyphosate(self):
        assert chemical_badges(Chemical.objects.get(pk=1)) == ['prop65', 'iarc_2a']

    def test_chlorpyrifos(self):
        assert chemical_badges(Chemical.objects.get(pk=2)) == ['carb_tac', 'california_restricted']

    def test_sulfur(self):
        assert chemical_badges(Chemical.objects.get(pk=3)) == []

    def test_every_badge_has_a_note(self):
        all_notes = notes.all_notes()
        assert all(badge['note'] in all_notes for badge in BADGES)
