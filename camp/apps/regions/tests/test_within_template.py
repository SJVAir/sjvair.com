from django.template.loader import render_to_string
from django.test import TestCase


def within(n_communities=0, n_districts=0, n_zips=0):
    return {
        'any': True,
        'counties': [{'name': 'Kern County', 'url': '/k/'}],
        'communities': [{'name': f'Place {i}', 'url': f'/p{i}/', 'type_label': 'City'} for i in range(n_communities)],
        'school_districts': [{'name': f'District {i}', 'url': f'/d{i}/'} for i in range(n_districts)],
        'zipcodes': [{'name': f'93{i:03d}', 'url': f'/z{i}/'} for i in range(n_zips)],
    }


class WithinTemplateTests(TestCase):
    def render(self, **counts):
        return render_to_string('regions/includes/within.html', {'within': within(**counts), 'within_name': 'Kern County', 'scope_qs': ''})

    def test_a_long_list_shows_a_dozen_and_a_show_all(self):
        html = self.render(n_communities=20, n_districts=5, n_zips=16)
        # Communities: 12 shown, 8 collapsed in the same list, one toggle.
        assert html.count('<li class="is-collapsed">') == 8
        assert 'data-show-label="Show all 20"' in html
        # Five districts fit: nothing collapsed, no toggle for them.
        assert 'Show all 5' not in html
        # ZIPs show 15 before collapsing.
        assert html.count('is-collapsed" href="/z') == 1 and 'Show all 16' in html

    def test_short_lists_have_no_toggle(self):
        html = self.render(n_communities=12, n_districts=12, n_zips=15)
        assert 'is-collapsed' not in html and 'data-collapse-toggle' not in html
