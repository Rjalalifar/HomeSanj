"""Independent metrics never turn missing labels into relevance judgments."""
import math
from datetime import datetime, timezone

import pytest

from backend.app.evaluation_metrics import ranking_metrics, qualified_success, grouped_bootstrap


def label(grade, hard='pass', origin='human'):
    return {'grade': grade, 'hard': hard, 'origin': origin}


def test_exponential_gain_and_fixed_reference_pool():
    result = ranking_metrics(['b', 'a'], {'a': label(3), 'b': label(2), 'c': label(1)})
    expected = (3 + 7 / math.log2(3)) / (7 + 3 / math.log2(3) + 1 / 2)
    assert result['ndcg_at_5']['value'] == pytest.approx(expected)
    assert result['precision_at_5']['value'] == .4
    assert result['recall_at_20_fixed_pool']['value'] == 1


def test_unknown_labels_and_hard_unknown_are_not_pass():
    result = ranking_metrics(['a', 'b'], {'a': label(None), 'b': label(3)})
    assert result['precision_at_5']['value'] is None
    assert result['mrr_at_5']['value'] is None
    assert result['human_hit_rate_at_5']['value'] == 1
    assert ranking_metrics(['a'], {'a': label(3, 'unknown')})['precision_at_5']['value'] is None


def test_empty_and_zero_ideal_have_documented_denominators():
    result = ranking_metrics([], {'a': label(0)})
    assert result['precision_at_5']['value'] == 0
    assert result['ndcg_at_5']['value'] is None
    assert result['ndcg_at_5']['reason'] == 'idcg_zero'
    assert result['recall_at_20_fixed_pool']['value'] is None


def test_ai_and_synthetic_are_not_human_hit_rate():
    result = ranking_metrics(['a'], {'a': label(3, origin='ai_weak')})
    assert result['human_hit_rate_at_5']['value'] is None
    assert result['judge_hit_rate_at_5']['value'] == 1


def test_qs_unknown_card_rejection_and_pending():
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    base = {'created_at': '2026-01-01T00:00:00+00:00', 'frozen_ids': ['a'],
            'hard_pass_ids': ['a'], 'completion_status': 'complete', 'feedback': []}
    tasks = [dict(base, feedback=[{'kind': 'top5', 'label': 'positive', 'candidate_ids': ['a']}]),
             dict(base, feedback=[{'kind': 'top5', 'label': 'negative', 'candidate_ids': []}]),
             dict(base, feedback=[{'kind': 'property', 'label': 'negative', 'candidate_ids': ['a']}]),
             dict(base, created_at='2026-01-02T23:00:00+00:00')]
    r = qualified_success(tasks, now=now)
    assert (r['N'], r['S'], r['F'], r['U'], r['pending']) == (3, 1, 1, 1, 1)
    assert r['qs_at_5']['value'] == .5
    assert r['missing_outcome_bounds'] == [1/3, 2/3]
    assert qualified_success([], now=now)['qs_at_5']['value'] is None


def test_group_bootstrap_requires_independent_groups():
    assert grouped_bootstrap([('same', .2), ('same', .4)])['status'] == 'insufficient_evidence'
    assert grouped_bootstrap([('a', .2), ('b', .4)], seed=4) == grouped_bootstrap([('a', .2), ('b', .4)], seed=4)
