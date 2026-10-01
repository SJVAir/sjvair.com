from django.template.loader import render_to_string
from django.test import TestCase


TABS = [
    {'key': 'overview', 'label': 'Overview', 'icon': 'fa-chart-pie', 'icon_class': 'is-map', 'url': '/o/', 'current': True},
    {'key': 'records', 'label': 'Records', 'icon': 'fa-table-list', 'icon_class': 'is-records', 'url': '/r/', 'current': False},
]
LINK = {'label': 'Pesticides', 'url': '/tools/pesticides/x/', 'icon': 'fa-spray-can-sparkles', 'icon_class': 'is-products'}


class AreaHeaderTemplateTests(TestCase):
    def render(self, **context):
        return render_to_string('regions/includes/area-header.html', {'name': 'Kern County', 'kind': 'County', **context})

    def test_tab_links_sit_at_the_row_end_never_current(self):
        html = self.render(tabs=TABS, tab_links=[LINK, dict(LINK, label='Other', url='/other/')])
        assert html.index('/r/') < html.index('/tools/pesticides/x/')
        assert html.count('class="is-cross-link"') == 1
        assert html.index('is-cross-link') < html.index('/tools/pesticides/x/') < html.index('/other/')
        assert html.count('aria-current="page"') == 1

    def test_a_tab_link_alone_still_shows_the_row(self):
        assert 'area-tabs' in self.render(tabs=TABS[:1], tab_links=[LINK])

    def test_one_tab_and_no_links_has_no_row(self):
        assert 'area-tabs' not in self.render(tabs=TABS[:1])
