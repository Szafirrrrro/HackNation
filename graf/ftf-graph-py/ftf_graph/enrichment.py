"""Join offline snapshot and laboratory features-v1. No inference or model downloads."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
import zipfile
from pathlib import Path


def confined(root, value):
    path = (root / value).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError('file outside feature corpus or missing')
    return path


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    p.chmod(0o600)


def prepare_model_input(snapshot, screenshot, output):
    """Make a corpus for existing extract.sh. Local content ID is not Meta library ID."""
    root, target = Path(snapshot).resolve(), Path(output).resolve()
    image = confined(root, screenshot)
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    ad_id = 'file-' + sha[:16]
    if target.exists():
        raise ValueError('model input directory already exists; choose a new directory')
    (target / 'media').mkdir(parents=True)
    image_name = 'media/' + image.name
    shutil.copyfile(image, target / image_name)
    write_json(target / 'manifest.json', {'schema_version': 'v0', 'dataset_id': target.name,
        'source_description': 'User-provided ad screenshot; local content identity only'})
    ad = {'ad_id': ad_id, 'source': {'kind': 'upload', 'provider': 'provided_snapshot'},
        'image_path': image_name, 'image_origin': 'sha256:' + sha}
    (target / 'ads.jsonl').write_text(json.dumps(ad, ensure_ascii=False) + '\n', encoding='utf-8')
    return ad_id


def merge_features(snapshot, feature_root, ad_id, *, methods=None, sources=None, page_link=None):
    """Merge a selected Ad only after image SHA matches the snapshot screenshot.

    methods: optional {destination: method_version}. Conflicting methods/origins are
    left unset rather than averaging incompatible vector spaces.
    """
    out = copy.deepcopy(snapshot)
    out["audio"] = {k: None for k in ("transcript", "segments", "asr_duration_s", "duration_s",
        "fingerprint", "speaker_embedding", "text_embedding")}
    root = Path(feature_root).resolve()
    methods = methods or {}
    sources = sources or {}
    ext = out.setdefault('extensions', {})
    extraction = out.setdefault('extraction', {})
    warnings = extraction.setdefault('warnings', [])
    evidence = extraction.setdefault('evidence', {})
    def warn(value):
        if value not in warnings:
            warnings.append(value)
    ads_path = root / 'ads.jsonl'
    ads = [json.loads(s) for s in ads_path.read_text(encoding='utf-8').splitlines() if s.strip()]
    selected = [a for a in ads if a.get('ad_id') == ad_id]
    if len(selected) != 1:
        raise ValueError('feature-ad-id must select exactly one source ad')
    ad = selected[0]
    if out.get('ad_id') not in (None, ad_id):
        raise ValueError('snapshot ad_id conflicts with feature ad_id')
    expected = None
    shot_sources = evidence.get('visual.phash', [])
    shot_files = {s.get('file') for s in shot_sources}
    for image in ext.get('images', []):
        if image.get('source', {}).get('file') in shot_files:
            expected = image.get('sha256')
    # Hash of original media is also saved by prepare workflow even without pHash libs.
    expected = expected or ext.get('selected_screenshot', {}).get('sha256')
    if ad.get('image_path') and not expected:
        raise ValueError('snapshot needs an explicitly selected screenshot with SHA-256')
    audio_field = next((k for k in ('audio_path', 'video_path') if ad.get(k)), None)
    audio_origin = ad.get('audio_origin') or (ad_id + '#' + audio_field if audio_field else None)
    corpus = read_json(root / 'corpus.json')
    fingerprint = corpus.get('fingerprint')
    if not fingerprint:
        raise ValueError('missing corpus fingerprint')
    # The laboratory copies ads.jsonl but not images; compare per-model image.sha256
    # or source image in the original input corpus if still present.
    source_root = Path(corpus.get('corpus_root', ''))
    original_sha = None
    try:
        original_image = confined(source_root.resolve(), ad.get('image_path', ''))
        original_sha = hashlib.sha256(original_image.read_bytes()).hexdigest()
    except (ValueError, OSError):
        pass
    # Match corpus._load_v0 origin priority; observation groups may live in original corpus.
    group = ad.get('observation_group')
    shots = source_root / 'observations/screenshots.jsonl'
    if not group and shots.is_file():
        for raw in shots.read_text(encoding='utf-8').splitlines():
            try:
                shot = json.loads(raw)
                if isinstance(shot, dict) and shot.get('ad_id') == ad_id:
                    group = shot.get('observation_group')
            except ValueError:
                continue
    image_origin = ad.get('image_origin') or group
    rows = []
    ext['model_unavailable'] = []
    for path in sorted((root / 'features').glob('*.jsonl')):
        run_path = root / 'runs' / (path.stem + '.json')
        try:
            run = read_json(run_path)
        except (OSError, ValueError):
            warn('model_run_missing: ' + path.name)
            continue
        if not isinstance(run, dict):
            warn('invalid_model_run: ' + path.name)
            continue
        if run.get('corpus_fingerprint') != fingerprint or run.get('status') != 'ok':
            warn('model_run_stale_or_failed: ' + path.name)
            continue
        for line, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            try:
                r = json.loads(raw)
            except ValueError:
                warn(f'invalid_feature_json: {path.name}:{line}')
                continue
            if not isinstance(r, dict):
                warn(f'invalid_feature_record: {path.name}:{line}')
                continue
            if r.get('ad_id') != ad_id:
                continue
            src = {'file': str(path.relative_to(root)), 'line': line,
                'method': r.get('method_version'), 'origin_id': r.get('origin_id'),
                'source_field': r.get('source_field'), 'feature_ad_id': ad_id,
                'corpus_fingerprint': fingerprint, 'source_ref': r.get('source_ref'),
                'family': r.get('family'), 'params': run.get('params')}
            if r.get('method_version') != run.get('method_version'):
                warn(f'model_method_mismatch: {path.name}:{line}')
                continue
            if r.get('status') != 'ok':
                ext['model_unavailable'].append({'field': r.get('field'), 'reason': r.get('reason'), **src})
                continue
            if not r.get('origin_id'):
                warn('model_origin_missing: ' + path.name)
                continue
            src['grouping'] = run.get('grouping', True)
            rows.append((r, src))
    shas = {r['value'] for r, _ in rows if r.get('field') == 'image.sha256' and isinstance(r.get('value'), str)}
    if original_sha:
        shas.add(original_sha)
    if expected and shas != {expected}:
        raise ValueError('screenshot SHA-256 missing, conflicting or different from model input')
    if not image_origin:
        bound_origins = {r.get('origin_id') for r, _ in rows if r.get('field') == 'image.sha256' and r.get('value') == expected and r.get('origin_id')}
        image_origin = next(iter(bound_origins)) if len(bound_origins) == 1 else ad_id + '#image_path'
    valid_rows = []
    for r, src in rows:
        derived = str(r.get('field', '')).startswith(('image.', 'face.', 'ocr.', 'qr.')) or str(r.get('source_field', '')).startswith('ocr.text@')
        audio_derived = str(r.get('field', '')).startswith(('audio.', 'asr.')) or str(r.get('source_field', '')).startswith('asr.text@')
        source_field = str(r.get('source_field', ''))
        text_origin = ad.get('text_origin') or (image_origin if ad.get('image_path') else ad_id + '#text')
        wrong_text = r.get('field') == 'text.embedding' and source_field == 'text' and r.get('origin_id') != text_origin
        if ((derived and (not expected or r.get('origin_id') != image_origin))
                or (audio_derived and (not audio_field or r.get('origin_id') != audio_origin)) or wrong_text):
            warn('model_origin_mismatch: ' + src['file'] + ':' + str(src['line']))
        else:
            valid_rows.append((r, src))
    rows = valid_rows
    ext['model_join'] = {'feature_ad_id': ad_id, 'corpus_fingerprint': fingerprint,
                         'image_sha256': expected, 'audio_source_field': audio_field, 'audio_origin': audio_origin, 'method': 'feature-join-v2'}
    # Local upload ID can be used by the engine, with its explicit namespace.
    if out.get('ad_id') is None:
        out['ad_id'] = ad_id
        evidence['ad_id'] = [{'file': 'ads.jsonl', 'method': 'explicit local corpus mapping; not Meta library identity'}]
    if isinstance(ad.get('text'), str) and ad['text'].strip():
        out['text']['ad_text'] = ad['text']
        evidence['text.ad_text'] = [{'file': 'ads.jsonl', 'field': 'text', 'origin_id': ad.get('text_origin'), 'method': 'source ad text'}]

    # A screenshot proves media identity, not that this landing page belongs to the ad.
    if page_link is not None:
        from urllib.parse import urlsplit
        ref = page_link.get('source_ref', {})
        def url_key(value):
            u = urlsplit(value or '')
            return (u.scheme.lower(), u.netloc.lower(), u.path or '/')
        if (page_link.get('ad_id') != ad_id or not page_link.get('capture_id')
                or not page_link.get('origin_id') or not page_link.get('observed_at')
                or not isinstance(ref, dict) or not all(ref.get(k) for k in ('file', 'field', 'value'))
                or not out.get('provenance', {}).get('url')
                or url_key(ref['value']) != url_key(out['provenance']['url'])):
            raise ValueError('invalid ad-page link: expected ad identity, capture, origin, time and source URL matching snapshot')
        ext['ad_page_link'] = copy.deepcopy(page_link)
    else:
        from .snapshot import empty_result
        blank = empty_result('')
        ext['page_observation'] = {k: copy.deepcopy(out[k]) for k in ('provenance', 'infra', 'page')}
        ext['page_observation']['extensions'] = {k: copy.deepcopy(v) for k, v in ext.items()
            if k not in ('page_observation', 'model_unavailable', 'model_join')}
        ext['page_observation']['evidence'] = copy.deepcopy(evidence)
        for k in ('infra', 'page'):
            out[k] = blank[k]
        for key in list(evidence):
            if key.startswith(('infra.', 'page.', 'extensions.')):
                evidence.pop(key)
        out['provenance']['url'] = None
        warn('ad_page_link_unverified: page observation retained separately; not an ad infrastructure proof')

    def vector(value):
        import numpy as np
        if not isinstance(value, dict) or not isinstance(value.get('vector'), str):
            raise ValueError('expected vector reference')
        matrix = np.load(confined(root, value['vector']), allow_pickle=False, mmap_mode='r')
        if not isinstance(matrix, np.ndarray):
            if hasattr(matrix, 'close'):
                matrix.close()
            raise ValueError('vector reference must point to NPY matrix')
        index, dim = value.get('row'), value.get('dim')
        if type(index) is not int or index < 0 or matrix.ndim != 2 or index >= matrix.shape[0] or dim != matrix.shape[1] or matrix.dtype.kind not in 'fi':
            raise ValueError('invalid vector shape/row/dim/type')
        v = [float(x) for x in matrix[index]]
        if not v or not all(math.isfinite(x) for x in v):
            raise ValueError('empty or nonfinite vector')
        return v

    def materialize(value):
        if isinstance(value, dict) and isinstance(value.get('vector'), str):
            return {**value, 'vector': vector(value)}
        if isinstance(value, dict) and isinstance(value.get('array'), str):
            import numpy as np
            archive = np.load(confined(root, value['array']), allow_pickle=False)
            if not isinstance(archive, np.lib.npyio.NpzFile):
                raise ValueError('array reference must point to NPZ archive')
            with archive:
                a = archive[value['key']]
                if list(a.shape) != value.get('shape') or str(a.dtype) != value.get('dtype') or a.dtype.kind not in 'fiu' or not np.isfinite(a).all():
                    raise ValueError('invalid array shape/dtype/values')
                return {**value, 'array': a.tolist()}
        return value

    # Lossless handoff of usable model fields, including ones the current scorer ignores.
    ext['model_features'] = []
    materialized = []
    for r, src in rows:
        try:
            value = materialize(r['value'])
            field = r.get('field')
            if field == 'audio.fingerprint':
                a = value.get('array') if isinstance(value, dict) else None
                if (not isinstance(a, list) or not a or value.get('dtype') != 'int32'
                        or value.get('shape') != [len(a)] or value.get('n_frames') != len(a)
                        or any(type(x) is not int or not -(2**31) <= x < 2**31 for x in a)):
                    raise ValueError('invalid Chromaprint int32 fingerprint')
            if field in ('audio.duration_s', 'asr.duration_s') and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError('invalid audio duration')
            if field == 'asr.text' and (not isinstance(value, str) or not value.strip()):
                raise ValueError('invalid transcript')
            if field == 'asr.segments':
                if not isinstance(value, list):
                    raise ValueError('invalid segments')
                for segment in value:
                    if (not isinstance(segment, dict) or not isinstance(segment.get('text'), str)
                            or any(type(segment.get(k)) not in (int, float) or not math.isfinite(segment[k]) for k in ('start', 'end'))
                            or not 0 <= segment['start'] <= segment['end']):
                        raise ValueError('invalid segment bounds')
            json.dumps(value, allow_nan=False)
            ext['model_features'].append({**r, 'value': value, 'evidence': src})
            if src['grouping'] is not False:
                materialized.append((r, src))
        except (ValueError, OSError, TypeError, KeyError, ImportError, EOFError, zipfile.BadZipFile) as exc:
            warn('invalid_model_feature: ' + str(r.get('field')) + ': ' + type(exc).__name__)
    rows = materialized

    groups = {}
    for r, src in rows:
        field, method = r.get('field'), r.get('method_version', '')
        target = None
        if field == 'ocr.text': target = 'text.ocr_text'
        elif field == 'image.phash': target = 'visual.phash'
        elif field == 'text.embedding':
            target = 'audio.text_embedding' if str(r.get('source_field', '')).startswith('asr.text@') else 'text.embedding'
        elif field in ('asr.text', 'asr.segments', 'asr.duration_s', 'audio.duration_s', 'audio.fingerprint', 'audio.speaker_embedding'):
            target = {'asr.text': 'audio.transcript', 'asr.segments': 'audio.segments',
                'asr.duration_s': 'audio.asr_duration_s'}.get(field, field)
        elif field == 'image.embedding':
            target = 'visual.clip_embedding' if 'clip' in method.lower() else 'extensions.image_embedding'
        elif field == 'face.embedding': target = 'faces'
        elif field in ('qr.values', 'qr.urls', 'ocr.urls', 'asr.text', 'text.topic', 'image.dhash'):
            target = 'extensions.' + field.replace('.', '_')
        if target:
            groups.setdefault(target, []).append((r, src))
    for target, candidates in groups.items():
        if target in methods:
            candidates = [(r, src) for r, src in candidates if r.get('method_version') == methods[target]]
        if target in sources:
            candidates = [(r, src) for r, src in candidates if r.get('source_field') == sources[target]]
        choices = {(r.get('method_version'), r.get('origin_id'), r.get('source_field')) for r, _ in candidates}
        if not choices:
            warn('selected_method_unavailable: ' + target)
            continue
        if len(choices) != 1:
            warn('ambiguous_model_or_origin: ' + target + '; select --method and/or --source for destination')
            continue
        try:
            if target == 'faces':
                value = []
                if any(not isinstance(r['value'], dict) for r, _ in candidates):
                    raise ValueError('face value must be an object')
                for r, src in sorted(candidates, key=lambda item: item[0]['value'].get('face_index', 0)):
                    f = r['value']
                    score = f.get('det_score')
                    if score is not None and (type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1):
                        raise ValueError('invalid detection score')
                    value.append({'person': None, 'similarity': None, 'quality': None, 'deepfake_score': None,
                        'embedding': vector(f), 'face_index': f.get('face_index'),
                        'bbox_xyxy': f.get('bbox_xyxy'), 'det_score': f.get('det_score')})
            else:
                # Duplicate observations are acceptable only if identical.
                values = [r['value'] for r, _ in candidates]
                if any(v != values[0] for v in values[1:]):
                    raise ValueError('conflicting observations')
                value = values[0]
                if target.endswith('embedding'):
                    value = vector(value)
                elif target == 'audio.fingerprint':
                    value = materialize(value)
                elif target in ('text.ocr_text',):
                    if not isinstance(value, str): raise ValueError('OCR must be a string')
                elif target == 'visual.phash':
                    if not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9]{16}', value): raise ValueError('invalid phash64')
            if target == 'faces':
                out['faces'] = value
            else:
                section, key = target.split('.', 1)
                out[section][key] = value
            evidence[target] = [src for _, src in candidates]
            if target.endswith('embedding') or target == 'faces':
                for r, src in candidates:
                    v = r['value']
                    src['vector_file'] = v['vector']
                    src['vector_row'] = v['row']
        except (ValueError, OSError, TypeError, KeyError, ImportError, EOFError, zipfile.BadZipFile) as exc:
            warn('invalid_model_feature: ' + target + ': ' + type(exc).__name__)
    # Keywords are observed phrases only, not generated labels or topic guesses.
    text = ' '.join(filter(None, (out['text'].get('ad_text'), out['text'].get('ocr_text'), out['audio'].get('transcript')))).lower()
    lexicon = ('inwestycja', 'inwestycje', 'orlen', 'pasywny dochód', 'kryptowaluty', 'bitcoin')
    out['text']['keywords'] = [k for k in lexicon if re.search(r'(?<!\w)' + re.escape(k) + r'(?!\w)', text)]
    if out['text']['keywords']:
        evidence['text.keywords'] = [{'method': 'observed-phrase-lexicon-v1', 'fields': ['text.ad_text', 'text.ocr_text', 'audio.transcript']}]
    warnings[:] = [w for w in warnings if not w.startswith('optional_models_not_configured:')]
    missing = [name for name, value in [('ocr', out['text'].get('ocr_text')), ('text_embedding', out['text'].get('embedding')), ('clip', out['visual'].get('clip_embedding')), ('faces', out.get('faces'))] if value is None or value == []]
    if missing:
        warn('model_fields_unavailable: ' + ', '.join(missing))
    warn('feature_join: unknown history, live status, RDAP, certificate, face identity and deepfake scores remain unfilled')
    if not rows:
        warn('no_usable_model_features')
    return out
