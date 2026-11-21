"""Synthetic vectors test serialization/joins, not model quality."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

try:
    import numpy as np
except ImportError:
    np = None

from ftf_graph.enrichment import merge_features, prepare_model_input, write_json
from ftf_graph.snapshot import empty_result, literal_config


@unittest.skipIf(np is None, 'numpy required for vector tests')
class MergeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sha = hashlib.sha256(b'image').hexdigest()
        self.image = self.root / 'image.png'
        self.image.write_bytes(b'image')
        self.record = empty_result('test')
        self.record['extensions']['selected_screenshot'] = {'file': 'screen.png', 'sha256': self.sha}
        self.ad = {'ad_id': 'a', 'image_origin': 'image-origin', 'image_path': 'image.png', 'text': 'Inwestycja w ORLEN'}
        (self.root / 'ads.jsonl').write_text(json.dumps(self.ad) + '\n')
        write_json(self.root / 'corpus.json', {'fingerprint': 'fp', 'corpus_root': str(self.root)})
        (self.root / 'features').mkdir()
        (self.root / 'runs').mkdir()
        (self.root / 'vectors').mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def add(self, slug, field, value, *, method=None, origin='image-origin', source='image_path', **extra):
        method = method or slug + '@v1'
        r = {'ad_id': 'a', 'field': field, 'value': value, 'status': 'ok', 'origin_id': origin,
             'method_version': method, 'source_field': source, **extra}
        (self.root / 'features' / (slug + '.jsonl')).write_text(json.dumps(r) + '\n')
        write_json(self.root / 'runs' / (slug + '.json'), {'corpus_fingerprint': 'fp', 'status': 'ok', 'method_version': method, 'grouping': True})
        return r

    def vec(self, name):
        np.save(self.root / 'vectors' / (name + '.npy'), np.array([[0.25, 0.75]], dtype=np.float32))
        return {'vector': 'vectors/' + name + '.npy', 'row': 0, 'dim': 2}

    def test_complete_join(self):
        self.add('ocr', 'ocr.text', 'Inwestycje bitcoin', method='ocr/tesseract@v1')
        self.add('dino', 'image.embedding', self.vec('dino'), method='image_embedding/dinov2@v1')
        self.add('clip', 'image.embedding', self.vec('clip'), method='image_embedding/clip@v1')
        self.add('text', 'text.embedding', self.vec('text'), method='text_embedding/e5@v1', source='ocr.text@ocr/tesseract@v1')
        self.add('face', 'face.embedding', {**self.vec('face'), 'face_index': 0, 'bbox_xyxy': [1, 2, 30, 40], 'det_score': 0.9})
        r = merge_features(self.record, self.root, 'a')
        self.assertEqual(r['ad_id'], 'a')
        self.assertEqual(r['text']['ocr_text'], 'Inwestycje bitcoin')
        self.assertEqual(r['text']['embedding'], [0.25, 0.75])
        self.assertEqual(r['visual']['clip_embedding'], [0.25, 0.75])
        self.assertEqual(r['extensions']['image_embedding'], [0.25, 0.75])
        self.assertIsNone(r['faces'][0]['quality'])
        self.assertIsNone(r['faces'][0]['deepfake_score'])
        self.assertIsNone(r['faces'][0]['person'])
        self.assertEqual(r['text']['keywords'], ['inwestycja', 'inwestycje', 'orlen', 'bitcoin'])
        self.assertEqual(r['extraction']['evidence']['text.embedding'][0]['origin_id'], 'image-origin')
        self.assertEqual(r, merge_features(self.record, self.root, 'a'))
        write_json(self.root / 'final.json', r)
        self.assertEqual(json.loads((self.root / 'final.json').read_text()), r)
        from ftf_graph.card import load_cards
        self.assertEqual(next(load_cards(str(self.root / 'final.json'))).id, 'a')
        import subprocess
        write_json(self.root / 'snapshot.json', self.record)
        proc = subprocess.run([sys.executable, '-B', '-m', 'ftf_graph', 'merge-features',
            str(self.root / 'snapshot.json'), '--features', str(self.root),
            '--feature-ad-id', 'a', '--out', str(self.root / 'cli.json')], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads((self.root / 'cli.json').read_text()), r)

    def test_observation_group_origin(self):
        del self.ad['image_origin']
        (self.root / 'ads.jsonl').write_text(json.dumps(self.ad) + '\n')
        (self.root / 'observations').mkdir()
        (self.root / 'observations/screenshots.jsonl').write_text(json.dumps({'ad_id': 'a', 'observation_group': 'group'}) + '\n')
        self.add('ocr', 'ocr.text', 'OK', origin='group')
        self.assertEqual(merge_features(self.record, self.root, 'a')['text']['ocr_text'], 'OK')

    def test_actual_feature_writer(self):
        from models.common.extractor import Extractor, FeatureWriter, Out
        from types import SimpleNamespace
        class Model(Extractor):
            name, use_case, version = 'test', 'ocr', 'synthetic'
        writer = FeatureWriter(self.root, Model())
        item = SimpleNamespace(ad_id='a', origin_id='image-origin', source_field='image_path', source_value='image.png')
        writer.add(item, [Out('ocr.text', 'written by actual writer')])
        writer.close({'status': 'ok', 'corpus_fingerprint': 'fp'})
        self.assertEqual(merge_features(self.record, self.root, 'a')['text']['ocr_text'], 'written by actual writer')

    def test_conflicting_identity_rejected(self):
        self.record['ad_id'] = 'other-emission'
        with self.assertRaisesRegex(ValueError, 'ad_id conflicts'):
            merge_features(self.record, self.root, 'a')

    def test_malformed_record_isolated(self):
        self.add('ocr', 'ocr.text', 'OK')
        with (self.root / 'features/ocr.jsonl').open('a') as f:
            f.write('[]\n')
        self.assertEqual(merge_features(self.record, self.root, 'a')['text']['ocr_text'], 'OK')

    def test_text_sources_require_selection(self):
        self.add('a', 'text.embedding', self.vec('a'), method='e5@v1', source='text')
        self.add('b', 'text.embedding', self.vec('b'), method='e5@v1', source='ocr.text@tesseract')
        self.assertIsNone(merge_features(self.record, self.root, 'a')['text']['embedding'])
        r = merge_features(self.record, self.root, 'a', sources={'text.embedding': 'ocr.text@tesseract'})
        self.assertEqual(r['text']['embedding'], [0.25, 0.75])

    def test_wrong_image_rejected(self):
        self.record['extensions']['selected_screenshot']['sha256'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            merge_features(self.record, self.root, 'a')

    def test_ambiguous_method_requires_choice(self):
        self.add('a', 'ocr.text', 'A')
        self.add('b', 'ocr.text', 'B')
        r = merge_features(self.record, self.root, 'a')
        self.assertIsNone(r['text']['ocr_text'])
        r = merge_features(self.record, self.root, 'a', methods={'text.ocr_text': 'b@v1'})
        self.assertEqual(r['text']['ocr_text'], 'B')

    def test_stale_unavailable_and_origin(self):
        self.add('stale', 'ocr.text', 'WRONG')
        write_json(self.root / 'runs/stale.json', {'status': 'ok', 'corpus_fingerprint': 'old'})
        self.add('wrong-origin', 'image.phash', 'a' * 16, origin='other')
        self.add('failed', 'ocr.text', None, status='unavailable', reason='no model')
        r = merge_features(self.record, self.root, 'a')
        self.assertIsNone(r['text']['ocr_text'])
        self.assertIsNone(r['visual']['phash'])
        self.assertEqual(r['extensions']['model_unavailable'][0]['reason'], 'no model')

    def test_bad_vector_does_not_break_other_fields(self):
        self.add('ocr', 'ocr.text', 'OK')
        self.add('clip', 'image.embedding', {'vector': '../escape.npy', 'dim': 2, 'row': 0}, method='clip@v1')
        r = merge_features(self.record, self.root, 'a')
        self.assertEqual(r['text']['ocr_text'], 'OK')
        self.assertIsNone(r['visual']['clip_embedding'])
        self.add('clip', 'image.embedding', {**self.vec('nan'), 'row': -1}, method='clip@v1')
        r = merge_features(self.record, self.root, 'a')
        self.assertIsNone(r['visual']['clip_embedding'])
        np.save(self.root / 'vectors/nan.npy', np.array([[float('nan'), 0.0]]))
        self.add('clip', 'image.embedding', {'vector': 'vectors/nan.npy', 'row': 0, 'dim': 2}, method='clip@v1')
        self.assertIsNone(merge_features(self.record, self.root, 'a')['visual']['clip_embedding'])

    def test_prepare_matches_latest_laboratory(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from models.common.corpus import load_corpus
        output = self.root / 'prepared'
        ad_id = prepare_model_input(self.root, 'image.png', output)
        corpus = load_corpus(output)
        self.assertEqual(corpus.ads[0].ad_id, ad_id)
        self.assertEqual(corpus.ads[0].image_origin, 'sha256:' + self.sha)

    def test_wrong_numpy_container_does_not_abort_join(self):
        self.add('ocr', 'ocr.text', 'OK')
        np.savez(self.root / 'wrong.npz', r0=np.array([1, 2]))
        self.add('clip', 'image.embedding', {'vector': 'wrong.npz', 'row': 0, 'dim': 2}, method='clip@v1')
        result = merge_features(self.record, self.root, 'a')
        self.assertEqual(result['text']['ocr_text'], 'OK')
        self.assertIsNone(result['visual']['clip_embedding'])
        (self.root / 'empty.npy').write_bytes(b'')
        self.add('clip', 'image.embedding', {'vector': 'empty.npy', 'row': 0, 'dim': 2}, method='clip@v1')
        self.assertEqual(merge_features(self.record, self.root, 'a')['text']['ocr_text'], 'OK')

    def audio_ad(self):
        self.ad = {'ad_id': 'a', 'video_path': 'clip.mp4'}
        (self.root / 'ads.jsonl').write_text(json.dumps(self.ad) + '\n')
        self.record = empty_result('test')
        self.record['provenance']['url'] = 'https://shop.example/offer'
        self.record['infra']['final_domain'] = 'shop.example'

    def write_audio(self):
        from models.common.extractor import Extractor, FeatureWriter, Out
        from types import SimpleNamespace
        class Model(Extractor):
            name, use_case, version, family = 'audio-test', 'asr', 'synthetic', 'audio'
        writer = FeatureWriter(self.root, Model())
        item = SimpleNamespace(ad_id='a', origin_id='a#video_path', source_field='video_path', source_value='clip.mp4')
        writer.add(item, [Out('asr.text', 'Inwestycja bitcoin', family='text'),
            Out('asr.segments', [{'start': 0.0, 'end': 2.0, 'text': 'Inwestycja bitcoin'}], family='text'),
            Out('asr.duration_s', 2.5, family='text'), Out('audio.duration_s', 2.4),
            Out('audio.fingerprint', {'array': np.array([-1, 42], dtype=np.int32), 'n_frames': 2}),
            Out('audio.speaker_embedding', np.array([0.6, 0.8], dtype=np.float32))])
        writer.close({'status': 'ok', 'corpus_fingerprint': 'fp'})

    def test_audio_writer_self_contained_and_no_unverified_page(self):
        self.audio_ad()
        self.write_audio()
        self.add('text-audio', 'text.embedding', self.vec('asr'), origin='a#video_path', source='asr.text@whisper')
        self.add('text-original', 'text.embedding', self.vec('orig'), origin='a#text', source='text')
        result = merge_features(self.record, self.root, 'a')
        audio = result['audio']
        self.assertEqual(audio['transcript'], 'Inwestycja bitcoin')
        self.assertEqual(audio['asr_duration_s'], 2.5)
        self.assertEqual(audio['duration_s'], 2.4)
        self.assertEqual(audio['fingerprint']['array'], [-1, 42])
        self.assertEqual(audio['text_embedding'], [0.25, 0.75])
        self.assertEqual(result['text']['embedding'], [0.25, 0.75])
        self.assertIsNone(result['infra']['final_domain'])
        self.assertFalse(any(k.startswith(('infra.', 'page.')) for k in result['extraction']['evidence']))
        self.assertEqual(result['extensions']['page_observation']['infra']['final_domain'], 'shop.example')
        self.assertEqual(len(result['extensions']['model_features']), 8)
        for src in result['extraction']['evidence']['audio.speaker_embedding']:
            self.assertEqual(src['origin_id'], 'a#video_path')
        write_json(self.root / 'final.json', result)
        import shutil
        shutil.rmtree(self.root / 'vectors')
        shutil.rmtree(self.root / 'arrays')
        from ftf_graph.card import load_cards
        self.assertEqual(next(load_cards(str(self.root / 'final.json'))).audio['fingerprint']['array'], [-1, 42])

    def test_audio_origin_missing_silent_and_array_validation(self):
        self.audio_ad()
        self.add('wrong', 'audio.speaker_embedding', self.vec('wrong'), origin='other', source='audio_path')
        self.add('silent', 'audio.fingerprint', None, origin=None, status='unavailable', reason='silent_audio')
        self.add('bad-array', 'audio.fingerprint', {'array': '../outside.npz', 'key': 'r0', 'shape': [2], 'dtype': 'int32', 'n_frames': 2}, origin='a#video_path', source='audio_path')
        r = merge_features(self.record, self.root, 'a')
        self.assertIsNone(r['audio']['fingerprint'])
        self.assertIsNone(r['audio']['speaker_embedding'])
        self.assertEqual(r['extensions']['model_unavailable'][0]['reason'], 'silent_audio')
        self.assertTrue(any('model_origin_mismatch' in w for w in r['extraction']['warnings']))
        np.savez(self.root / 'wrong.npz', r0=np.array([1.5, 2.5]))
        self.add('bad-array', 'audio.fingerprint', {'array': 'wrong.npz', 'key': 'r0', 'shape': [2], 'dtype': 'float64', 'n_frames': 2}, origin='a#video_path', source='audio_path')
        self.assertIsNone(merge_features(self.record, self.root, 'a')['audio']['fingerprint'])

    def test_audio_method_selection_and_excluded_features(self):
        self.audio_ad()
        self.add('one', 'asr.text', 'one', origin='a#video_path', source='audio_path')
        self.add('two', 'asr.text', 'two', origin='a#video_path', source='audio_path')
        self.assertIsNone(merge_features(self.record, self.root, 'a')['audio']['transcript'])
        self.assertEqual(merge_features(self.record, self.root, 'a', methods={'audio.transcript': 'two@v1'})['audio']['transcript'], 'two')
        self.add('excluded', 'audio.speaker_embedding', self.vec('excluded'), origin='a#video_path', source='audio_path')
        write_json(self.root / 'runs/excluded.json', {'status': 'ok', 'corpus_fingerprint': 'fp', 'method_version': 'excluded@v1', 'grouping': False})
        r = merge_features(self.record, self.root, 'a')
        self.assertIsNone(r['audio']['speaker_embedding'])
        self.assertTrue(any(f['evidence']['grouping'] is False for f in r['extensions']['model_features']))

    def test_explicit_page_link_and_conflicts(self):
        self.audio_ad()
        self.write_audio()
        link = {'ad_id': 'a', 'capture_id': 'capture-1', 'origin_id': 'export-1',
            'observed_at': '2026-11-21T10:00:00Z', 'source_ref': {'file': 'export.json', 'field': 'landing_url', 'value': 'https://shop.example/offer'}}
        r = merge_features(self.record, self.root, 'a', page_link=link)
        self.assertEqual(r['infra']['final_domain'], 'shop.example')
        link['ad_id'] = 'other'
        with self.assertRaisesRegex(ValueError, 'ad-page link'):
            merge_features(self.record, self.root, 'a', page_link=link)


class ParsingTest(unittest.TestCase):
    def test_snapshot_cli_without_site_packages(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            fixture = Path(__file__).parent / 'fixtures/snapshot'
            proc = subprocess.run([sys.executable, '-S', '-B', '-m', 'ftf_graph',
                'extract-snapshot', str(fixture), '--out', str(Path(folder) / 'snapshot.json')],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)


    def test_json_parse_literal(self):
        config = {'visit': {'fields': {'fb_ad_id': '123'}}, 'secret': 'do not export'}
        js = 'window.aio = JSON.parse(' + repr(json.dumps(config)) + ');'
        self.assertEqual(literal_config(js), config)
        with self.assertRaises(ValueError):
            literal_config("window.aio = JSON.parse(fetch('/secret')); ")
