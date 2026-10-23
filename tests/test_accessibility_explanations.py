"""Explanation claims distinguish stop proximity from measured pedestrian travel."""
from backend.app.explanations import eligible_snapshot, template_explanation
from tests.test_search import database
from tests.test_accessibility import auto_state, submit, process, Routes


def test_stop_explanation_uses_route_and_proximity_as_separate_facts(database):
    rid = submit(database, auto_state(property={'parking_required': True}))
    process(database, Routes())
    snapshot, rows = eligible_snapshot(database, rid)
    explanation = template_explanation(snapshot, rows)
    assert explanation['evidence']['property:p1:straight_line_meters']['value'] == 111.2
    assert explanation['evidence']['property:p1:walk_distance_meters']['value'] == 150
    claims = [c['claim']['field'] for c in explanation['recommendations'][0]['strengths']]
    assert 'straight_line_meters' in claims and 'walk_duration_seconds' in claims
    assert 'transfers' not in claims


def test_destination_failure_still_allows_known_property_explanations(database):
    rid = submit(database, auto_state(destination={'latitude': 1.1, 'longitude': .5, 'confirmed': True},
        property={'parking_required': True}))
    process(database, Routes('timeout'))
    snapshot, rows = eligible_snapshot(database, rid)
    assert len(rows) == 1
    explanation = template_explanation(snapshot, rows)
    assert explanation['evidence']['property:p1:total_duration_seconds']['value'] is None
    assert explanation['evidence']['property:p1:monthly_rent_toman']['value'] == 10
