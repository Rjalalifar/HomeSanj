# OTP connection report

The installed root UI declared `/otp/transmodel/v3` through its linked JavaScript.
Introspection and a coordinate routing contract were successful from the backend Python
network environment. Version 2.10.0; internal timezone Asia/Tehran. Five routes validated.
`root_reachable=true`, `routing_api_verified=true`, `fixture_mode=false`.

Evidence lives in data/otp/. Only BUS has been observed and enabled. No aggregate
transfer count is exposed by the installed schema, so transfers remain null. Schedule
basis and graph/feed version remain unknown. Observed routes have no realtime updates.
The global lines query fails upstream, while quay/journey/trip queries work.

Exact repeat command:
`python -m backend.app.otp_probe --contract data/otp/contract-input.json`.
Docker/cloud networking has not been tested. No port changes, graph rebuild, install,
tunnel or public exposure occurred.
