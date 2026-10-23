"""OTP timestamps have second precision; automatic inputs must use that precision."""
from datetime import datetime
from backend.app.accessibility import prepare_state
from tests.test_accessibility import auto_state


def test_automatic_request_time_uses_otp_second_precision():
    state = prepare_state(auto_state(destination={'latitude': 35.7, 'longitude': 51.4, 'confirmed': True}))
    assert datetime.fromisoformat(state.accessibility.effective_at).microsecond == 0
    assert state.travel.time.microsecond == 0
