from django.test import TestCase

from camp.apps.entries import levels


class GuidelinesPagesTests(TestCase):
    def test_general_page_from_metadata(self):
        response = self.client.get('/guidelines/')
        assert response.status_code == 200
        html = response.content.decode()
        for level in levels.PM25:
            assert str(level.label) in html, level.key
        assert '0.0 – 9.0 µg/m³' in html
        assert '0 – 50' in html
        for level in list(levels.PM25)[1:]:
            assert str(level.guidance) in html, level.key
        assert 'background-color: #00e400' in html
        assert "It's a great day to be active outside" not in html
        assert 'Consider reducing prolonged or heavy exertion' not in html
        assert 'Guidelines are based on hourly PM2.5 concentration.' in html

    def test_schools_page_from_metadata(self):
        response = self.client.get('/guidelines/schools/')
        assert response.status_code == 200
        html = response.content.decode()
        assert 'Athletic Practice &amp; Training' in html
        assert '2-4 hours' in html
        assert 'Exercise indoors or limit vigorous outdoor activities to a maximum of 15 minutes.' in html
        assert '≥225.5' in html
        assert 'background-color: #7e0023' in html

    def test_guidelines_pages_query_count(self):
        # Measured on the old static templates: no queries for an anonymous visitor.
        for url in ('/guidelines/', '/guidelines/schools/'):
            self.client.get(url)
            with self.assertNumQueries(0):
                assert self.client.get(url).status_code == 200
