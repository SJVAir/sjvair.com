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

    def test_tab_links_sit_on_the_title_line_never_current(self):
        html = self.render(tabs=TABS, tab_links=[LINK, dict(LINK, label='Other', url='/other/')])
        # Beside the title, before the tab row: small buttons, in order, never current.
        assert html.index('/tools/pesticides/x/') < html.index('/other/') < html.index('area-tabs')
        assert html.count('class="button is-small is-rounded area-cross-link"') == 2
        assert html.count('aria-current="page"') == 1

    def test_a_tab_link_alone_shows_no_row(self):
        html = self.render(tabs=TABS[:1], tab_links=[LINK])
        assert 'area-tabs' not in html and 'area-cross-link' in html

    def test_the_summary_table_toggle_ends_the_row(self):
        subviews = [
            {'key': 'summary', 'label': 'Summary', 'icon': 'fa-chart-pie', 'url': '/o/', 'current': True},
            {'key': 'table', 'label': 'Table', 'icon': 'fa-table', 'url': '/o/table/', 'current': False},
        ]
        html = self.render(tabs=TABS, subviews=subviews)
        row = html[html.index('area-tabs-row'):]
        assert row.index('/r/') < row.index('subview-toggle') < row.index('href="/o/table/"')
        assert 'class="button is-selected is-link is-light" href="/o/"' in row
        assert 'subview-toggle' not in self.render(tabs=TABS)

    def test_one_tab_and_no_links_has_no_row(self):
        assert 'area-tabs' not in self.render(tabs=TABS[:1])

    def test_an_internal_header_link_stays_in_the_tab(self):
        html = self.render(header_links=[
            {'label': 'Fresno urban area', 'url': '/ua/', 'internal': True},
            {'label': 'Community page', 'url': 'https://example.com/'},
        ])
        assert '<a class="button is-small is-rounded area-switch" href="/ua/">' in html and 'Fresno urban area</span></a>' in html
        assert '<a href="https://example.com/" target="_blank" rel="noopener">Community page</a>' in html
