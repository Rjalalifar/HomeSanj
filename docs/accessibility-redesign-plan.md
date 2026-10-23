# Property accessibility redesign

The approved user specification replaces manual journey planning with automatic property accessibility. Reuse the existing search, Leaflet map, SQLite route cache, OTP adapter, semantic retrieval and review/evaluation systems.

## Decisions

- Opt in through `state.accessibility.semantics_version=accessibility-1`; old states without this field retain their legacy interpretation. New UI defaults opt in.
- Persist one optional destination in this browser; never put coordinates in URLs or events. Origins always come from immutable candidate property coordinates.
- Execute automatic destination routing at current Asia/Tehran time, with a documented short cache window; retain the exact time of a reused response. Stop routing uses an explicitly verified pedestrian profile. Cache pedestrian routes separately from transit schedules.
- Keep every hard-property-eligible result visible, with independent accessibility status. Save nearest-stop evidence before routing, so an OTP failure cannot erase straight-line distance. Retain immutable candidate evidence with an additive migration.
- Extend the existing bounded durable worker and route cache. Select alternative itineraries and sort already returned evidence on reads without new OTP calls or modifying historical snapshots.
- Use separate versioned recommended profiles for destination and nearby-stop modes. Sort valid known measurements before unknown and break ties deterministically by property ID.
- Reuse Phase 3 replay/feedback; preserve version and hashes of new evidence while keeping old replay semantics unchanged.

## Execution and verification

1. Verify real stop source and pedestrian OTP request from installed schema/data.
2. Add automatic state, cache, candidate evidence, worker integration and sort views with offline regression tests.
3. Update the existing frontend/map and tests for destination lifecycle, contextual sorts and asynchronous cancellation.
4. Run all backend/frontend tests, build, isolated browser workflow and bounded actual OTP checks; measure filtering/proximity/cache work over the stored 5,655 listings.
5. Record observed results, remaining unavailable evidence and repeatable commands in the handoff. No unexecuted checks are marked successful.
