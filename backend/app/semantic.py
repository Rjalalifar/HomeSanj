"""Local multilingual embeddings and a disposable, reconciled Qdrant search index."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid5

import httpx
from dotenv import load_dotenv
from sqlalchemy import select

from .db import Database, Listing, utcnow
from .normalize import normalize_text

MODEL = 'Xenova/multilingual-e5-small'
MODEL_REVISION = '761b726dd34fb83930e26aab4e9ac3899aa1fa78'
DIMENSIONS = 384
DESCRIPTION_VERSION = 'known-facts-fa-1'
NAMESPACE = UUID('83216e90-97a9-50fa-99f2-2b129f98ecaa')
PAYLOAD_INDEXES = {
    'property_id': 'keyword', 'dataset_version': 'keyword', 'embedding_version': 'keyword',
    'is_active': 'bool', 'is_demo': 'bool', 'neighborhood_id': 'keyword',
    'district_id': 'keyword', 'rent': 'integer', 'deposit': 'integer',
    'bedrooms': 'integer', 'area': 'float', 'parking': 'keyword', 'elevator': 'keyword',
}


class SemanticUnavailable(RuntimeError):
    """A recoverable advanced-search dependency or index failure."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass
class SemanticSettings:
    url: str = 'http://127.0.0.1:6333'
    api_key: str = ''
    collection: str = 'homesanj_properties_v1'
    enabled: bool = True
    model: str = MODEL
    revision: str = MODEL_REVISION
    model_dir: str = './runtime/models/multilingual-e5-small'
    candidates: int = 100
    timeout: float = 5
    batch_size: int = 16
    threads: int = 2

    @classmethod
    def from_env(cls):
        load_dotenv()
        result = cls(url=os.getenv('QDRANT_URL', cls.url).rstrip('/'),
            api_key=os.getenv('QDRANT_API_KEY', ''), collection=os.getenv('QDRANT_COLLECTION', cls.collection),
            enabled=os.getenv('QDRANT_ENABLED', 'true').lower() == 'true',
            model=os.getenv('EMBEDDING_MODEL', MODEL), revision=os.getenv('EMBEDDING_MODEL_VERSION', MODEL_REVISION),
            model_dir=os.getenv('EMBEDDING_MODEL_DIR', cls.model_dir),
            candidates=max(1, min(500, int(os.getenv('ADVANCED_VECTOR_CANDIDATES', '100')))),
            timeout=max(1, min(30, float(os.getenv('QDRANT_TIMEOUT_SECONDS', '5')))),
            batch_size=max(1, min(64, int(os.getenv('EMBEDDING_BATCH_SIZE', '16')))),
            threads=max(1, min(8, int(os.getenv('EMBEDDING_CPU_THREADS', '2')))))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', result.collection):
            raise ValueError('Invalid Qdrant collection name')
        if os.getenv('EMBEDDING_PROVIDER', 'local') != 'local':
            raise ValueError('Only the verified local embedding provider is supported')
        return result

    @property
    def index_version(self):
        return f'{self.model}@{self.revision}:q8:mean-l2:{DIMENSIONS}:{DESCRIPTION_VERSION}'

    @property
    def manifest_path(self):
        name = hashlib.sha256(f'{self.url}/{self.collection}'.encode()).hexdigest()[:20]
        return Path('runtime/semantic') / f'{name}.json'


def point_id(property_id):
    """Map arbitrary canonical IDs to stable, valid Qdrant UUID identifiers."""
    return str(uuid5(NAMESPACE, str(property_id)))


def _availability(value):
    return 'present' if value is True else 'absent' if value is False else 'unknown'


def factual_document(item, geo):
    """Exclude raw source text and private/user fields from the shared vector index."""
    neighborhood = None
    identifier = item.get('neighborhood_id')
    if identifier:
        try:
            neighborhood = geo.feature(identifier)['properties']['name_fa']
        except KeyError:
            pass
    parts = ['آپارتمان اجاره‌ای']
    if neighborhood:
        parts.append(f'محله {neighborhood}')
    for key, label in (('bedrooms', 'اتاق خواب'), ('area_m2', 'متر مربع'),
                       ('monthly_rent_toman', 'تومان اجاره ماهانه'), ('deposit_toman', 'تومان ودیعه')):
        if item.get(key) is not None:
            parts.append(f'{item[key]} {label}')
    for key, label in (('parking', 'پارکینگ'), ('elevator', 'آسانسور')):
        if item.get(key) is True:
            parts.append(f'دارای {label}')
        elif item.get(key) is False:
            parts.append(f'بدون {label}')
    if item.get('is_synthetic'):
        parts.append('آگهی نمایشی با قیمت فرضی')
    source_ids = sorted({str(row.get('source', '')) for row in item.get('source_records', [])})
    district_ids = []
    if item.get('latitude') is not None and item.get('longitude') is not None:
        district_ids = geo.district_memberships(item['longitude'], item['latitude'])
    payload = {'property_id': item['property_id'], 'dataset_version': item['dataset_version'],
        'listing_updated_at': item.get('collected_at') or item.get('published_at'),
        'is_active': item.get('is_active', True) is not False, 'is_demo': item.get('is_synthetic', False),
        'neighborhood_id': identifier, 'district_id': district_ids,
        'rent': item.get('monthly_rent_toman'), 'deposit': item.get('deposit_toman'),
        'bedrooms': item.get('bedrooms'), 'area': item.get('area_m2'),
        'parking': _availability(item.get('parking')), 'elevator': _availability(item.get('elevator')),
        'source_id': source_ids, 'language': 'fa', 'safe_tags': ['rental_apartment'],
        'description': normalize_text('؛ '.join(parts)), 'description_version': DESCRIPTION_VERSION}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                          separators=(',', ':')).encode()).hexdigest()
    payload['content_fingerprint'] = fingerprint
    return payload


class LocalEncoder:
    """Run the pinned public ONNX encoder on CPU with E5 prefix/pooling semantics."""
    _instances = {}
    _load_lock = threading.Lock()

    def __init__(self, settings):
        if settings.model != MODEL or settings.revision != MODEL_REVISION:
            raise SemanticUnavailable('embedding_model_version_not_verified')
        self.settings = settings
        self.path = Path(settings.model_dir)
        self.lock = threading.Lock()
        manifest_file = self.path / 'manifest.json'
        if not manifest_file.exists():
            raise SemanticUnavailable('embedding_model_not_downloaded')
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        if manifest.get('model') != MODEL or manifest.get('revision') != MODEL_REVISION:
            raise SemanticUnavailable('embedding_model_version_mismatch')
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        for filename in ('tokenizer.json', 'onnx/model_quantized.onnx'):
            actual = hashlib.sha256((self.path / filename).read_bytes()).hexdigest()
            if manifest.get('sha256', {}).get(filename) != actual:
                raise SemanticUnavailable('embedding_model_checksum_mismatch')
        self.np = np
        self.tokenizer = Tokenizer.from_file(str(self.path / 'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=192)
        self.tokenizer.enable_padding(pad_id=1, pad_token='<pad>')
        options = ort.SessionOptions()
        options.intra_op_num_threads = settings.threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(self.path / 'onnx/model_quantized.onnx'),
            sess_options=options, providers=['CPUExecutionProvider'])
        self.input_names = {entry.name for entry in self.session.get_inputs()}
        self.encode(['آپارتمان دو خوابه'], query=True)

    @classmethod
    def get(cls, settings):
        key = (settings.model_dir, settings.model, settings.revision, settings.threads)
        with cls._load_lock:
            if key not in cls._instances:
                cls._instances[key] = cls(settings)
            return cls._instances[key]

    def encode(self, texts, *, query=False):
        if not texts:
            return []
        np = self.np
        prefix = 'query: ' if query else 'passage: '
        with self.lock:
            tokens = self.tokenizer.encode_batch([prefix + normalize_text(text)[:4000] for text in texts])
            mask = np.asarray([token.attention_mask for token in tokens], dtype=np.int64)
            inputs = {'input_ids': np.asarray([token.ids for token in tokens], dtype=np.int64),
                      'attention_mask': mask,
                      'token_type_ids': np.asarray([token.type_ids for token in tokens], dtype=np.int64)}
            outputs = self.session.run(None, {key: value for key, value in inputs.items() if key in self.input_names})
        hidden = outputs[0]
        if hidden.ndim != 3 or hidden.shape[-1] != DIMENSIONS:
            raise SemanticUnavailable('embedding_dimension_mismatch')
        vectors = (hidden * mask[:, :, None]).sum(axis=1) / mask.sum(axis=1)[:, None].clip(min=1)
        vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True).clip(min=1e-12)
        if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5):
            raise SemanticUnavailable('embedding_invalid_vector')
        return vectors.astype(np.float32).tolist()


def download_model(settings):
    if settings.model != MODEL or settings.revision != MODEL_REVISION:
        raise SemanticUnavailable('embedding_model_version_not_verified')
    target = Path(settings.model_dir)
    target.mkdir(parents=True, exist_ok=True)
    hashes = {}
    with httpx.Client(timeout=httpx.Timeout(180, connect=30), follow_redirects=True) as client:
        for name in ('config.json', 'tokenizer.json', 'tokenizer_config.json', 'onnx/model_quantized.onnx'):
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                temporary = path.with_suffix(path.suffix + '.partial')
                with client.stream('GET', f'https://huggingface.co/{MODEL}/resolve/{MODEL_REVISION}/{name}') as response:
                    response.raise_for_status()
                    with temporary.open('wb') as handle:
                        for chunk in response.iter_bytes(1024 * 1024):
                            handle.write(chunk)
                temporary.replace(path)
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {'model': MODEL, 'revision': MODEL_REVISION, 'dimensions': DIMENSIONS,
                'sha256': hashes, 'downloaded_at': utcnow(), 'quantization': 'q8',
                'pooling': 'attention-mask mean; L2 normalized', 'max_tokens': 192}
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    encoder = LocalEncoder(settings)
    vector = encoder.encode(['آپارتمان اجاره‌ای با دو اتاق خواب و آسانسور'], query=True)[0]
    return {**manifest, 'verified_dimensions': len(vector), 'verified_norm': sum(x*x for x in vector) ** .5,
            'status': 'passed'}


class QdrantHTTP:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.client = httpx.Client(base_url=settings.url, timeout=settings.timeout,
            headers={'api-key': settings.api_key} if settings.api_key else {}, transport=transport)
        self.path = '/collections/' + settings.collection

    def close(self):
        self.client.close()

    def request(self, method, path, *, body=None, allow_missing=False):
        try:
            response = self.client.request(method, path, json=body)
            if allow_missing and response.status_code == 404:
                return None
            if response.status_code in (401, 403):
                raise SemanticUnavailable('qdrant_authorization_failed')
            response.raise_for_status()
            value = response.json()
            if value.get('status') != 'ok':
                raise SemanticUnavailable('qdrant_invalid_response')
            return value.get('result')
        except httpx.TimeoutException as exc:
            raise SemanticUnavailable('qdrant_timeout') from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise SemanticUnavailable('qdrant_unavailable') from exc

    def info(self):
        result = self.request('GET', self.path, allow_missing=True)
        if result is not None:
            vector = result.get('config', {}).get('params', {}).get('vectors', {})
            if vector.get('size') != DIMENSIONS or vector.get('distance') != 'Cosine':
                raise SemanticUnavailable('qdrant_vector_schema_mismatch')
        return result

    def ensure(self):
        if self.info() is None:
            self.request('PUT', self.path, body={'vectors': {'size': DIMENSIONS, 'distance': 'Cosine'}})
        for name, kind in PAYLOAD_INDEXES.items():
            self.request('PUT', self.path + '/index?wait=true', body={'field_name': name, 'field_schema': kind})

    def scroll(self):
        found, offset = {}, None
        while True:
            body = {'limit': 256, 'with_payload': ['property_id', 'content_fingerprint', 'embedding_version', 'is_active'],
                    'with_vector': False}
            if offset is not None:
                body['offset'] = offset
            result = self.request('POST', self.path + '/points/scroll', body=body)
            for point in result['points']:
                found[str(point['id'])] = point.get('payload') or {}
            offset = result.get('next_page_offset')
            if offset is None:
                return found


class SemanticService:
    def __init__(self, db, geo, settings=None, *, client_factory=QdrantHTTP, encoder_factory=LocalEncoder.get):
        self.db, self.geo = db, geo
        self.settings = settings or SemanticSettings.from_env()
        self.client_factory, self.encoder_factory = client_factory, encoder_factory
        self._query_semaphore = asyncio.Semaphore(1)

    def canonical(self, eligible_ids=None):
        with self.db.session() as session:
            statement = select(Listing).order_by(Listing.property_id)
            if eligible_ids is not None:
                if not eligible_ids:
                    return {}
                statement = statement.where(Listing.property_id.in_(list(eligible_ids)))
            return {row.property_id: factual_document(row.payload, self.geo) for row in session.scalars(statement)
                    if row.is_synthetic or any(record.get('raw', {}).get('public_listing') is True
                                               for record in row.payload.get('source_records', []))}

    def reconcile(self, *, index=False, rebuild=False):
        started = time.perf_counter()
        documents = self.canonical()
        active = {key: value for key, value in documents.items() if value['is_active']}
        client = self.client_factory(self.settings)
        try:
            if index:
                client.ensure()
            elif client.info() is None:
                raise SemanticUnavailable('qdrant_collection_missing')
            collection_info = client.info() or {}
            missing_indexes = sorted(set(PAYLOAD_INDEXES) - set(collection_info.get('payload_schema', {})))
            existing = client.scroll()
            wrong_version = [key for key, value in existing.items() if value.get('embedding_version') != self.settings.index_version]
            if index and wrong_version and not rebuild:
                raise SemanticUnavailable('qdrant_model_version_mismatch_rebuild_required')
            current_ids = {point_id(identifier) for identifier in active}
            deleted = sorted(set(existing) - current_ids)
            changed = [identifier for identifier, item in active.items()
                       if existing.get(point_id(identifier), {}).get('content_fingerprint') != item['content_fingerprint']
                       or existing.get(point_id(identifier), {}).get('embedding_version') != self.settings.index_version
                       or existing.get(point_id(identifier), {}).get('is_active') is not True]
            changed.sort()
            missing = sum(point_id(identifier) not in existing for identifier in changed)
            report = {'status': 'drift' if changed or deleted or missing_indexes else 'healthy', 'canonical_count': len(active),
                'indexed_count': len(existing), 'missing_count': missing, 'stale_count': len(changed) - missing,
                'orphan_count': len(deleted), 'wrong_version_count': len(wrong_version), 'missing_payload_indexes': missing_indexes,
                'index_version': self.settings.index_version, 'collection': self.settings.collection,
                'changed_property_ids': changed, 'orphan_point_ids': deleted, 'upserted_count': 0,
                'deleted_count': 0, 'verified_at': utcnow()}
            if index:
                encoder = self.encoder_factory(self.settings) if changed else None
                for start in range(0, len(changed), self.settings.batch_size):
                    identifiers = changed[start:start + self.settings.batch_size]
                    vectors = encoder.encode([active[identifier]['description'] for identifier in identifiers])
                    points = [{'id': point_id(identifier), 'vector': vector,
                               'payload': {**active[identifier], 'embedding_version': self.settings.index_version}}
                              for identifier, vector in zip(identifiers, vectors)]
                    client.request('PUT', client.path + '/points?wait=true', body={'points': points})
                    report['upserted_count'] += len(points)
                    if report['upserted_count'] % 256 == 0 or report['upserted_count'] == len(changed):
                        print(json.dumps({'indexed': report['upserted_count'], 'pending': len(changed) - report['upserted_count']}), flush=True)
                for start in range(0, len(deleted), 256):
                    batch = deleted[start:start + 256]
                    client.request('POST', client.path + '/points/delete?wait=true', body={'points': batch})
                    report['deleted_count'] += len(batch)
                report.update(status='healthy', indexed_count=len(active), missing_count=0, stale_count=0,
                              orphan_count=0, wrong_version_count=0, missing_payload_indexes=[], verified_at=utcnow())
                self.settings.manifest_path.parent.mkdir(parents=True, exist_ok=True)
                self.settings.manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            report['latency_ms'] = round((time.perf_counter() - started) * 1000, 2)
            return report
        finally:
            client.close()

    async def retrieve(self, text, eligible_ids):
        """Return retrieval signals only; callers retain every exact eligible candidate."""
        start = time.perf_counter()
        ids = list(dict.fromkeys(eligible_ids))
        output = {'property_ids': [], 'scores': {}, 'retrieved_count': 0, 'eligible_count': len(ids),
                  'coverage': 0.0 if ids else 1.0, 'status': 'not_requested', 'partial': bool(ids),
                  'index_version': self.settings.index_version, 'policy_version': 'vector-overretrieve-3x-v1',
                  'is_probability': False, 'stale_hit_count': 0}
        if not self.settings.enabled:
            output.update(status='degraded', reason='qdrant_disabled')
        elif not text.strip() or not ids:
            output.update(status='empty_query' if not text.strip() else 'no_eligible_candidates')
        else:
            try:
                async with self._query_semaphore:
                    output.update(await asyncio.to_thread(self._retrieve, text, ids))
            except SemanticUnavailable as exc:
                output.update(status='degraded', reason=exc.reason)
            except (OSError, ImportError, KeyError, ValueError) as exc:
                output.update(status='degraded', reason='embedding_or_index_unavailable')
        output['latency_ms'] = round((time.perf_counter() - start) * 1000, 2)
        return output

    def _retrieve(self, text, eligible_ids):
        client = self.client_factory(self.settings)
        try:
            info = client.info()
            if info is None:
                raise SemanticUnavailable('qdrant_collection_missing')
            if not info.get('points_count'):
                raise SemanticUnavailable('qdrant_index_empty')
            manifest_path = self.settings.manifest_path
            if not manifest_path.exists():
                raise SemanticUnavailable('qdrant_index_not_reconciled')
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest.get('index_version') != self.settings.index_version:
                raise SemanticUnavailable('qdrant_index_version_mismatch')
            documents = self.canonical(eligible_ids)
            documents = {key: value for key, value in documents.items() if value['is_active']}
            vector = self.encoder_factory(self.settings).encode([text], query=True)[0]
            limit = min(len(documents), self.settings.candidates * 3)
            if not limit:
                return {'status': 'no_eligible_candidates', 'property_ids': [], 'scores': {}, 'retrieved_count': 0}
            result = client.request('POST', client.path + '/points/query', body={'query': vector,
                'limit': limit, 'with_payload': ['property_id', 'content_fingerprint', 'embedding_version'],
                'filter': {'must': [{'has_id': [point_id(identifier) for identifier in documents]},
                                  {'key': 'is_active', 'match': {'value': True}},
                                  {'key': 'embedding_version', 'match': {'value': self.settings.index_version}}]}})
            accepted, scores, stale = [], {}, 0
            for hit in result.get('points', []):
                payload = hit.get('payload') or {}
                identifier = payload.get('property_id')
                canonical = documents.get(identifier)
                if (canonical is None or str(hit.get('id')) != point_id(identifier)
                    or payload.get('content_fingerprint') != canonical['content_fingerprint']
                    or payload.get('embedding_version') != self.settings.index_version):
                    stale += 1
                    continue
                if identifier not in scores:
                    accepted.append(identifier)
                    scores[identifier] = float(hit['score'])
            accepted = accepted[:self.settings.candidates]
            scores = {identifier: scores[identifier] for identifier in accepted}
            return {'status': 'ok' if accepted else 'degraded',
                    'reason': 'stale_index_hits_rejected' if stale else 'no_indexed_eligible_records' if not accepted else None,
                    'property_ids': accepted, 'scores': scores, 'retrieved_count': len(accepted),
                    'eligible_count': len(documents), 'coverage': len(accepted) / len(documents),
                    'partial': len(accepted) < len(documents), 'stale_hit_count': stale,
                    'overretrieved_count': len(result.get('points', [])), 'approximate_retrieval': True}
        finally:
            client.close()


def reciprocal_rank_fusion(*ranked_lists, constant=60):
    """Return rank signals, not probabilities or evidence of a property attribute."""
    scores = {}
    for ranked in ranked_lists:
        for rank, identifier in enumerate(dict.fromkeys(ranked), start=1):
            scores[identifier] = scores.get(identifier, 0) + 1 / (constant + rank)
    return sorted(scores, key=lambda identifier: (-scores[identifier], identifier)), scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['download-model', 'index', 'reconcile', 'health', 'query'])
    parser.add_argument('--rebuild', action='store_true')
    parser.add_argument('--text', default='آپارتمان دو خوابه با پارکینگ و آسانسور')
    parser.add_argument('--report')
    args = parser.parse_args()
    settings = SemanticSettings.from_env()
    try:
        if args.command == 'download-model':
            result = download_model(settings)
        else:
            from .config import Settings
            from .geo import GeometryStore
            application = Settings.from_env()
            database = Database(application.database_url)
            service = SemanticService(database, GeometryStore(application.data_dir), settings)
            if args.command in ('index', 'reconcile', 'health'):
                result = service.reconcile(index=args.command == 'index', rebuild=args.rebuild)
            else:
                result = asyncio.run(service.retrieve(args.text, list(service.canonical())))
    except (SemanticUnavailable, httpx.HTTPError, ImportError, OSError) as exc:
        result = {'status': 'unavailable', 'reason': getattr(exc, 'reason', type(exc).__name__)}
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    displayed = {key: value for key, value in result.items()
                 if key not in {'changed_property_ids', 'orphan_point_ids', 'property_ids', 'scores'}}
    if 'property_ids' in result:
        displayed['first_property_ids'] = result['property_ids'][:5]
    print(json.dumps(displayed, ensure_ascii=False, indent=2))
    return 0 if result.get('status') in ('healthy', 'passed', 'ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
