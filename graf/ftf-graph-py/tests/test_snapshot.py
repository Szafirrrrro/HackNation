"""Own synthetic material; no organizer assets or remote requests."""
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ftf_graph.snapshot import Document, extract_snapshot, literal_config, write_snapshot
from ftf_graph.card import parse_card


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, value):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(value.encode() if isinstance(value, str) else value)

    def entry(self, url, mime='text/html', body='', **kwargs):
        e = {'request': {'url': url, 'method': 'GET'}, 'response': {'status': 200,
            'content': {'mimeType': mime, 'text': body}}, 'pageref': 'page-1',
            'startedDateTime': '2026-10-09T08:24:11Z'}
        e.update(kwargs)
        return e

    def har(self, entries, pages=None):
        self.put('zapis.har', json.dumps({'log': {'entries': entries, 'pages': pages or []}}))

    def example(self):
        html = '''<!-- saved from url=(0030)https://evil.example/article -->
        <html><head><title>Gazeta.pl</title><link rel="icon" href="/favicon.ico"></head><body>
        <h1>Własny przykład</h1><p>Kontakt +48 123 456 789 <a href="https://t.me/demo_operator">Telegram</a></p>
        <div hidden>Ukryty tekst</div><script src="Zażółć pliki/main.js.pobrane"></script>
        <script src="Zażółć pliki/fbevents.js.pobrane"></script><script>
        fbq('init', '123456789'); gtag('config','AW-123'); gtag('config', 'G-ABC123');
        window.aio = {visit: {fields: {fb_pixel: '99887766', fb_ad_id: '44', fb_campaign_id: '55', fb_ad_set_id: '66', token: 'SECRET'}}, campaign: {uuid: 'internal', owner_uuid: 'owner'}, landing: {uuid: 'land', lander_template_uuid: 'tpl', lander_type_uuid: 'type'}};
        fetch('/api/lead');</script></body></html>'''
        self.put('«Wiem» — strona.html', html)
        js = b"console.log('own synthetic JS');"
        self.put('Zażółć pliki/main.js.pobrane', js)
        self.put('Zażółć pliki/fbevents.js.pobrane', 'var commonSDK = true;')
        start = self.entry('https://front.example/start', 'text/html')
        start['response'].update(status=302, redirectURL='https://evil.example/article')
        main = self.entry('https://evil.example/article', body=html, serverIPAddress='192.0.2.7')
        script = self.entry('https://evil.example/main.js', 'application/javascript', base64.b64encode(js).decode())
        script['response']['content']['encoding'] = 'base64'
        pixel = self.entry('https://www.facebook.com/tr/?id=22334455', 'image/gif')
        pixel['request'].update(method='POST', postData={'text': 'phone=+48111999888&token=PRIVATE'})
        broken = self.entry('https://evil.example/broken.js', 'application/javascript', '###')
        broken['response']['content']['encoding'] = 'base64'
        self.har([start, main, script, pixel, broken], [{'title': 'https://front.example/start'}])
        return js

    def test_full_offline(self):
        js = self.example()
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            result = extract_snapshot(self.root)
        self.assertEqual(result, extract_snapshot(self.root))
        self.assertIsNone(result['ad_id'])
        self.assertEqual(result['provenance']['url'], 'https://front.example/start')
        self.assertEqual(result['provenance']['fetched_at'], '2026-10-09T08:24:11Z')
        self.assertEqual(result['infra']['final_domain'], 'evil.example')
        self.assertEqual(result['infra']['redirect_chain'], ['https://front.example/start', 'https://evil.example/article'])
        self.assertEqual(result['infra']['dns']['ip'], '192.0.2.7')
        self.assertEqual(result['extensions']['tracking_ids']['meta_pixel'], ['123456789', '22334455', '99887766'])
        self.assertEqual(result['page']['tracking_ids']['ga'], 'G-ABC123')
        self.assertEqual(result['extensions']['tracking_ids']['google_ads'], ['AW-123'])
        self.assertEqual(result['extensions']['aio']['campaign.uuid'], ['internal'])
        self.assertEqual(result['extensions']['aio']['visit.fields.fb_campaign_id'], ['55'])
        serialized = json.dumps(result)
        self.assertNotIn('PRIVATE', serialized)
        self.assertNotIn('SECRET', serialized)
        self.assertNotIn('111999888', serialized)
        self.assertIsNone(result['page']['form_endpoint'])
        self.assertEqual(result['extensions']['post_requests'][0]['kind'], 'telemetry')
        self.assertIsNone(result['text']['ad_text'])
        self.assertIsNone(result['first_seen'])
        self.assertEqual(result['status'], 'unknown')
        self.assertTrue(any('invalid_har_body' in x for x in result['extraction']['warnings']))
        h = hashlib.sha256(js).hexdigest()
        self.assertEqual(result['page']['script_hashes'].count(h), 1)
        self.assertEqual(len(next(x for x in result['extensions']['scripts'] if x['sha256'] == h)['sources']), 2)
        card = parse_card(result)
        self.assertEqual(card.id, '')
        self.assertNotIn('ip', [a.kind for a in card.artifacts])
        sdk = next(x for x in result['extensions']['scripts'] if x['common_library'])
        self.assertNotIn(sdk['sha256'], [a.value for a in card.artifacts])

    def test_missing_and_malformed(self):
        self.put('invalid.har', '{broken')
        self.har([None, {'request': None, 'response': None}, self.entry('https://asset.example/image', 'image/png', 'broken')])
        r = extract_snapshot(self.root)
        self.assertIsNone(r['provenance']['url'])
        self.assertIsNone(r['page']['dom_template_hash'])
        self.assertTrue(r['extraction']['warnings'])

    def test_dom_and_hidden(self):
        self.put('a', '<html><body><p id="a">One</p><script>var x=1</script></body></html>')
        a = extract_snapshot(self.root)
        self.put('a', '<html><!-- c --><body><p id="b">Two</p><script>var x=2</script></body></html>')
        b = extract_snapshot(self.root)
        self.assertEqual(a['page']['dom_template_hash'], b['page']['dom_template_hash'])
        self.assertIsNone(a['page']['hidden_text_hash'])
        self.assertEqual(Document('<p style="display:none">A</p><p>B</p>').hidden, ['A'])

    def test_url_conflict_and_form(self):
        self.put('strona', '<!-- saved from url=(0020)https://other.example/ --><html><form action="/lead"></form><script src="missing.js"></script></html>')
        self.har([self.entry('https://main.example/')])
        r = extract_snapshot(self.root)
        self.assertEqual(r['provenance']['url'], 'https://main.example/')
        self.assertEqual(r['page']['form_endpoint'], 'https://main.example/lead')
        self.assertTrue(any('url_conflict' in w for w in r['extraction']['warnings']))
        self.assertTrue(any('script_body_missing' in w for w in r['extraction']['warnings']))

    def test_untrusted_urls_and_boolean_attributes(self):
        self.put('page', '<html><body style aria-hidden><link rel href="x"><script src="http://["></script><script>fbq("init","12345678")</script></body></html>')
        self.har([self.entry('http://[', 'text/plain', 'abc')])
        r = extract_snapshot(self.root)
        self.assertEqual(len(r['page']['script_hashes']), 1)
        self.assertIsNone(r['provenance']['url'])

    def test_resource_redirect_is_not_navigation(self):
        css = self.entry('https://cdn.example/theme.css', 'text/css', _resourceType='stylesheet')
        css['response'].update(status=302, redirectURL='https://page.example/')
        page = self.entry('https://page.example/', body='<html></html>', _resourceType='document')
        self.har([css, page])
        r = extract_snapshot(self.root)
        self.assertEqual(r['provenance']['url'], 'https://page.example/')
        self.assertEqual(r['infra']['redirect_chain'], [])

    def test_aio_pixel_has_direct_evidence(self):
        self.put('page', '<html><script>window.aio={visit:{fields:{fb_pixel:"123"}}};</script></html>')
        r = extract_snapshot(self.root)
        self.assertEqual(r['page']['tracking_ids']['meta_pixel'], '123')
        self.assertTrue(r['extraction']['evidence']['page.tracking_ids.meta_pixel'])

    def test_safe_aio(self):
        self.assertEqual(literal_config('window.aio = {visit:{fields:{fb_pixel:"12"}}};')['visit']['fields']['fb_pixel'], '12')
        for text in ('window.aio = run();', 'window.aio = {a: function(){evil()}};', 'window.aio = {} + evil();'):
            with self.assertRaises(ValueError):
                literal_config(text)

    def test_cli_without_graph_dependencies(self):
        self.put('strona', '<html><p>Żółć</p></html>')
        target = Path(self.tmp.name).parent / (self.root.name + '-output.json')
        try:
            p = subprocess.run([sys.executable, '-m', 'ftf_graph', 'extract-snapshot', str(self.root), '--out', str(target)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(target.read_text())['extensions']['landing_text'], 'Żółć')
        finally:
            target.unlink(missing_ok=True)

    def test_symlink_escape(self):
        self.put('page', '<html></html>')
        (self.root / 'escape').symlink_to('/etc/passwd')
        self.assertEqual(extract_snapshot(self.root)['extensions']['landing_text'], '')

    def test_images_and_har_favicon(self):
        try:
            from PIL import Image
            import imagehash
            import mmh3
        except ImportError:
            self.skipTest('optional image dependencies unavailable')
        import io
        b = io.BytesIO()
        Image.new('RGB', (32, 32), 'red').save(b, format='PNG')
        data = b.getvalue()
        self.put('zrzut bez rozszerzenia', data)
        self.put('bad.png', b'\x89PNGbroken')
        self.put('page', '<html><link rel="icon" href="https://demo.example/favicon.ico"></html>')
        e = self.entry('https://demo.example/favicon.ico', 'image/png', base64.b64encode(data).decode())
        e['response']['content']['encoding'] = 'base64'
        self.har([e])
        r = extract_snapshot(self.root, screenshot='zrzut bez rozszerzenia')
        self.assertIsNotNone(r['visual']['phash'])
        self.assertEqual(r['infra']['favicon']['mmh3'], mmh3.hash(base64.encodebytes(data), signed=True))
        self.assertEqual(r['infra']['favicon']['phash'], r['visual']['phash'])
        self.assertTrue(any('unreadable' in w for w in r['extraction']['warnings']))
        self.assertIsNone(extract_snapshot(self.root)['visual']['phash'])
        # A HAR copy and an earlier local copy must not suppress selected OCR.
        self.put('a-earlier-copy', data)
        from types import SimpleNamespace
        class OCR:
            name, use_case, modality, method_version = 'fake-ocr', 'ocr', 'image', 'synthetic-test-v1'
            calls = 0
            def extract(self, item):
                self.calls += 1
                return [SimpleNamespace(field='ocr.text', value='own test text')]
        model = OCR()
        r = extract_snapshot(self.root, screenshot='zrzut bez rozszerzenia', extractors=[model])
        self.assertEqual(r['text']['ocr_text'], 'own test text')
        self.assertEqual(model.calls, 1)


if __name__ == '__main__':
    unittest.main()
