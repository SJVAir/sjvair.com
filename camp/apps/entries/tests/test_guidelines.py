from django.test import RequestFactory, TestCase
from django.urls import reverse

from camp.apps.entries import levels
from camp.apps.entries.guidelines import SCHOOL_ACTIVITIES, school_guidelines_json


class SchoolGuidelinesTests(TestCase):
    def by_key(self):
        return {a.key: a for a in SCHOOL_ACTIVITIES}

    def test_level_keys_match_pm25(self):
        # Adding or renaming a PM2.5 level must fail here, not serve a level with no text.
        pm25_keys = [lvl.key for lvl in levels.PM25]
        for activity in SCHOOL_ACTIVITIES:
            assert list(activity.levels) == pm25_keys, activity.key

    def test_activity_order_and_labels(self):
        assert [a.key for a in SCHOOL_ACTIVITIES] == ['recess', 'pe', 'athletics', 'events']
        assert [str(a.label) for a in SCHOOL_ACTIVITIES] == [
            'Recess', 'P.E.', 'Athletic Practice & Training', 'Scheduled Sporting Events',
        ]
        assert [a.duration and str(a.duration) for a in SCHOOL_ACTIVITIES] == [
            '15 minutes', '1 hour', '2-4 hours', None,
        ]

    def test_text_verbatim(self):
        acts = self.by_key()
        assert tuple(map(str, acts['recess'].levels['unhealthy'])) == (
            'Exercise indoors or avoid vigorous outdoor activities.',
            'Sensitive individuals should remain indoors.',
        )
        assert str(acts['pe'].levels['unhealthy'][0]) == (
            'Exercise indoors or limit vigorous outdoor activities to a maximum of 15 minutes.'
        )
        assert str(acts['events'].levels['unhealthy_sensitive'][0]) == (
            'Increase rest breaks and substitutions per CIF guidelines for extreme heat.'
        )
        for activity in SCHOOL_ACTIVITIES:
            assert tuple(map(str, activity.levels['hazardous'])) == ('No outdoor or indoor activities.',)

    def test_json_values_are_plain_str(self):
        # Lazy translation proxies must not leak out of the JSON block.
        block = school_guidelines_json(RequestFactory().get('/'))

        def leaves(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    assert type(k) is str
                    yield from leaves(v)
            elif isinstance(node, (list, tuple)):
                for v in node:
                    yield from leaves(v)
            else:
                yield node

        assert all(type(v) is str or v is None for v in leaves(block))

    def test_source_url_follows_the_route(self):
        request = RequestFactory().get('/')
        block = school_guidelines_json(request)
        assert block['source']['url'] == request.build_absolute_uri(reverse('guidelines-schools'))
