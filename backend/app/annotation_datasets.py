"""Immutable JSONL annotation exports with linked-group splits and conservative imports."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from sqlalchemy import select, text
from .db import utcnow
from .feedback import ReviewSample, ReviewAnnotation
from .evaluation_store import DatasetVersion
from .evaluation_replay import digest
from .evaluation_metrics import RUBRIC_VERSION


def group_split(group_id, seed=17):
    value = int(hashlib.sha256(f'{seed}:{group_id}'.encode()).hexdigest()[:8], 16) % 100
    return 'train' if value < 70 else 'validation' if value < 85 else 'holdout'


def linked_groups(samples):
    parents = {s.task_id: s.task_id for s in samples}
    def root(k):
        while parents[k] != k:
            parents[k] = parents[parents[k]]
            k = parents[k]
        return k
    seen = {}
    for sample in sorted(samples, key=lambda s: s.task_id):
        state = deepcopy(sample.evidence.get('confirmed_state'))
        if state:
            state.pop('state_revision', None)
        keys = [('task', sample.task_id), ('property', sample.candidate_id)]
        if state:
            keys.append(('intent', digest(state)))
        for key in keys:
            if key in seen:
                a, b = sorted([root(sample.task_id), root(seen[key])])
                parents[b] = a
            else:
                seen[key] = sample.task_id
    return {task: root(task) for task in parents}


def export_dataset(db, directory='runtime/datasets', seed=17):
    with db.session() as session:
        samples = {s.sample_id: s for s in session.scalars(select(ReviewSample))}
        groups = linked_groups(list(samples.values()))
        rows = []
        for annotation in session.scalars(select(ReviewAnnotation).order_by(ReviewAnnotation.annotation_id)):
            sample = samples.get(annotation.sample_id)
            if not sample:
                continue
            metadata = deepcopy(annotation.annotation_data)
            if metadata.get('operations'):
                metadata['operations'] = [p for p in metadata['operations'] if p['field'] not in ('travel.destination', 'query')]
            rows.append({'annotation_id': annotation.annotation_id, 'sample_id': sample.sample_id,
                'request_id': sample.request_id, 'snapshot_id': sample.snapshot_id, 'task_id': sample.task_id,
                'group_id': groups[sample.task_id], 'split': group_split(groups[sample.task_id], seed),
                'candidate_id': sample.candidate_id, 'actor_cohort': sample.actor_kind,
                'synthetic': sample.actor_kind != 'real_user', 'origin': metadata.get('origin', 'ai_weak' if annotation.needs_human_review else 'human'),
                'review_status': metadata.get('review_status', 'legacy_binary_not_graded'),
                'grade': metadata.get('grade'), 'annotation_type': metadata.get('type', 'legacy_binary'),
                'data': metadata, 'evidence_refs': annotation.evidence_refs,
                'manifest_id': sample.evidence.get('manifest_id'), 'source_versions': sample.evidence.get('versions', {}),
                'frozen_evidence_reference': {'table': 'review_samples', 'sample_id': sample.sample_id},
                'evidence_hash': digest(sample.evidence), 'content_hash': annotation.content_hash,
                'created_at': annotation.created_at})
    data = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows)
    manifest = {'schema_version': 'annotation-jsonl-1', 'rubric_version': RUBRIC_VERSION,
        'split_seed': seed, 'split_policy': 'linked_task_property_confirmed_intent_70_15_15',
        'task_groups': {task: {'group_id': group, 'split': group_split(group, seed)} for task, group in sorted(groups.items())},
        'count': len(rows), 'independent_groups': len({r['group_id'] for r in rows}),
        'sha256': hashlib.sha256(data.encode()).hexdigest(), 'source': 'existing_review_annotations',
        'human_real_graded': sum(r['origin'] == 'human' and not r['synthetic'] and r['grade'] is not None for r in rows),
        'holdout_policy': 'final_milestone_only; not acquisition, prompts or tuning'}
    dataset_id = 'annotations_' + digest(manifest)[:24]
    target = Path(directory) / dataset_id
    target.mkdir(parents=True, exist_ok=True)
    for filename, contents in [('annotations.jsonl', data), ('manifest.json', json.dumps({'dataset_id': dataset_id, **manifest}, ensure_ascii=False, indent=2))]:
        path = target / filename
        if path.exists() and path.read_text(encoding='utf-8') != contents:
            raise ValueError('Immutable dataset version conflicts with existing bytes')
        if not path.exists():
            path.write_bytes(contents.encode('utf-8'))
    with db.session.begin() as session:
        if not session.get(DatasetVersion, dataset_id):
            session.add(DatasetVersion(dataset_id=dataset_id, manifest=manifest, created_at=utcnow()))
    return {'dataset_id': dataset_id, **manifest, 'path': str(target)}


def import_dataset(db, directory):
    folder = Path(directory)
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    raw = (folder / 'annotations.jsonl').read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['sha256']:
        raise ValueError('Dataset checksum mismatch')
    rows = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line]
    if len(rows) != manifest['count'] or len({r['annotation_id'] for r in rows}) != len(rows):
        raise ValueError('Dataset count or duplicate identity mismatch')
    added = duplicates = 0
    with db.session() as session:
        session.execute(text('BEGIN IMMEDIATE'))
        for row in rows:
            if row['grade'] not in (None, 0, 1, 2, 3) or row['split'] != group_split(row['group_id'], manifest['split_seed']):
                raise ValueError('Invalid grade or group split')
            existing = session.get(ReviewAnnotation, row['annotation_id'])
            if existing:
                if existing.content_hash != row['content_hash']:
                    raise ValueError('Immutable annotation identity conflict')
                duplicates += 1
                continue
            sample = session.get(ReviewSample, row['sample_id'])
            if not sample or digest(sample.evidence) != row['evidence_hash'] or sample.snapshot_id != row['snapshot_id']:
                raise ValueError('Source sample/evidence unavailable; import requires matching evidence')
            if row['synthetic'] != (sample.actor_kind != 'real_user') or not set(row['evidence_refs']) <= set(sample.evidence.get('facts', {})):
                raise ValueError('Provenance or evidence reference mismatch')
            metadata = row['data'] | {'approval_state': 'pending', 'review_status': 'imported_unverified'}
            session.add(ReviewAnnotation(annotation_id=row['annotation_id'], sample_id=sample.sample_id,
                reviewer_id='dataset_import', idempotency_key=row['annotation_id'], content_hash=row['content_hash'],
                annotation_kind='imported_pending', label='uncertain', reason_code=None, evidence_refs=row['evidence_refs'],
                needs_human_review=True, model_version=None, annotation_data=metadata, created_at=row['created_at']))
            added += 1
        session.commit()
    return {'status': 'ok', 'inserted': added, 'duplicates': duplicates, 'human_gold_auto_approved': False}
