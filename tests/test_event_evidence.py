from backend.app.feedback import actor_kind
from backend.app.event_evidence import qualifying_alternatives


def test_fixture_routes_are_demo_evidence_even_for_real_property():
    assert actor_kind({'results': [{'property': {'is_synthetic': False},
                                   'selected_itinerary': {'source_kind': 'synthetic_fixture'}}]}) == 'demo'


def test_only_alternatives_passing_every_condition_are_exposed_as_qualified():
    evaluation = {'itineraries': [{'itinerary_id': 'fast'}, {'itinerary_id': 'eligible'}, {'itinerary_id': 'unknown'}],
                  'itinerary_evaluations': [
                      {'itinerary_id': 'fast', 'verdicts': [{'verdict': 'pass'}, {'verdict': 'fail'}]},
                      {'itinerary_id': 'eligible', 'verdicts': [{'verdict': 'pass'}]},
                      {'itinerary_id': 'unknown', 'verdicts': [{'verdict': 'unknown'}]}]}
    assert qualifying_alternatives(evaluation) == [{'itinerary_id': 'eligible'}]
