from django.test import TestCase


class SiteChromeTests(TestCase):
    def test_landmarks_and_labels(self):
        for url in ['/', '/about/', '/alerts/', '/contact/']:
            response = self.client.get(url, follow=True)
            assert response.status_code == 200, url
            html = response.content.decode()
            assert html.count('<main') == 1, url
            assert '<main id="main"' in html
            assert 'class="skip-link" href="#main"' in html
            assert 'id="id_translate" aria-label="Language"' in html
            assert '<h4' not in html


class ReportPrefillTests(TestCase):
    URL = '/contact/'

    def get(self, page, topic='Report'):
        params = {'page': page}
        if topic:
            params['topic'] = topic
        return self.client.get(self.URL, params).context['form']

    def test_report_prefill(self):
        page = 'https://testserver/workspace/shared/abc123'
        form = self.get(page)
        assert form.initial['topic'] == 'Report'
        assert form.initial['subject'] == 'Report a shared dashboard'
        assert form.initial['message'].startswith(f'Page: {page}')
        assert 'Report' in dict(form.fields['topic'].choices)

    def test_relative_page_accepted(self):
        form = self.get('/workspace/shared/abc123')
        assert form.initial['message'].startswith('Page: /workspace/shared/abc123')

    def test_foreign_page_ignored(self):
        for page in [
            'https://evil.com/workspace/shared/abc',
            '//evil.com/workspace/shared/abc',
            'javascript:alert(1)//workspace/shared/abc',
            'ftp://testserver/workspace/shared/abc',
            '/elsewhere/workspace/shared/abc',
            '/workspace/shared/' + 'a' * 500,
        ]:
            form = self.get(page)
            assert 'message' not in form.initial, page
            assert 'subject' not in form.initial, page

    def test_no_prefill_without_topic(self):
        form = self.get('/workspace/shared/abc', topic=None)
        assert 'message' not in form.initial
