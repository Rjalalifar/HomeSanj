"""Quota shortages are filled by random acquisition, with critical work outside quota."""
from backend.app.review_sampling import select_batch, classify


def test_seeded_random_fills_shortages_without_duplicates():
    frames = {(f'r{i}', f'p{i}'): ({'mode': 'normal' if i%2 else 'advanced', 'task_id': f't{i%3}'}, {}, 'novelty') for i in range(40)}
    strata = {'critical': [('r0', 'p0')], 'novelty': list(frames)[1:]}
    first = select_batch(frames, strata, 20, 17)
    assert first == select_batch(frames, strata, 20, 17)
    assert len(first) == 21 and len({x[0] for x in first}) == 21
    assert sum(x[1] == 'random' for x in first) == 16
    assert all(p is None for _, kind, p in first if kind != 'random')
    assert first != select_batch(frames, strata, 20, 18)


def test_disagreement_requires_observed_signal():
    row = {'property': {'property_id': 'p', 'monthly_rent_toman': 1, 'deposit_toman': 1, 'parking': True, 'elevator': False}}
    assert classify(row, {}, set()) == ('novelty', 'low_label_coverage')
    replay = {'retrieval': {'retrieval_signals': {'p': {'vector_rank': 1, 'lexical_rank': None}}}}
    assert classify(row, replay, set()) == ('disagreement', 'vector_lexical_disagreement')
