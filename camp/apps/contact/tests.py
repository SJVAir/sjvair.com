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
