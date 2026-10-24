"""Keep the public page, README media, and contributor credits consistent."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.elements = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class PresentationTests(unittest.TestCase):
    def test_product_notes_use_sentra_names_and_preserve_source_records(self):
        paths = [ROOT / 'README.md', ROOT / 'site/index.html', * (ROOT / 'docs').rglob('*.md')]
        for path in paths:
            self.assertNotRegex(path.read_text(encoding='utf-8'), r'(?i)(?<![a-z])(orca|coucou)(?![a-z])', str(path))
        index = json.loads((ROOT / 'vendor/component-records/index.json').read_text())
        for record in index['records']:
            self.assertEqual(hashlib.sha256((ROOT / record['archived']).read_bytes()).hexdigest(), record['sha256'])
        self.assertTrue((ROOT / 'THIRD_PARTY_NOTICES.md').is_file())

    def test_page_is_english_and_local_links_resolve(self):
        source = (ROOT / 'site/index.html').read_text(encoding='utf-8')
        page = Page(source)
        self.assertIn(('html', {'lang': 'en'}), page.elements)
        ids = {attrs['id'] for _, attrs in page.elements if 'id' in attrs}
        for tag, attrs in page.elements:
            for key in ('src', 'href'):
                value = attrs.get(key, '')
                if value.startswith('#') and len(value) > 1:
                    self.assertIn(value[1:], ids)
                elif value and not value.startswith(('https://', '#')):
                    self.assertTrue((ROOT / 'site' / value).is_file(), value)
            if tag == 'img':
                self.assertTrue(attrs.get('alt'))
        for translated in ('Skip to content', 'Main navigation', 'Download APK', 'No installable iPhone app'):
            self.assertIn(translated, source)
        for old in ('pt-BR', 'Baixar APK', 'Carregando disponibilidade', 'Antes de começar'):
            self.assertNotIn(old, source)

    def test_readme_uses_current_demonstration_screenshots(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        provenance = json.loads((ROOT / 'site/assets/provenance.json').read_text())
        self.assertTrue(provenance['fixture'])
        self.assertFalse(provenance['production_account'])
        self.assertIn('isolated demonstration data', readme)
        for name, digest in provenance['sha256'].items():
            self.assertIn('site/assets/' + name, readme)
            self.assertEqual(hashlib.sha256((ROOT / 'site/assets' / name).read_bytes()).hexdigest(), digest)
        self.assertNotRegex(readme, r'!\[[^\]]*\]\(docs/media/2026-10-13/')

    def test_contributor_images_are_local_and_verified(self):
        folder = ROOT / 'docs/media/contributors'
        provenance = json.loads((folder / 'provenance.json').read_text())
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('https://github.com/Kayn3x', readme)
        self.assertNotIn('https://github.com/Predo-kn', readme)
        for person in provenance['contributors']:
            image = folder / person['file']
            self.assertIn('docs/media/contributors/' + person['file'], readme)
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), person['sha256'])
            self.assertTrue(image.read_bytes().startswith(bytes.fromhex('ffd8ff')))


if __name__ == '__main__':
    unittest.main()
