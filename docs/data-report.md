# Data report

Source dataset `tehran-2020-v1`, transform `geometry-v1`, EPSG:32639 for metrics.
Actual transform: 377 neighborhoods, 22 districts, 2 repaired self-intersections,
120 overlap pairs above 1 m², 108 neighborhoods above 1% outside assigned district,
11 above 50%. Original geometry and hashes are preserved in data/raw and validation-report.

Full deterministic seed: 5655 generated, 1885 in each series, no shortages. The first
30 were inserted by the small vertical seed; full seed skipped those and inserted 5625.
See data/seed-report.json for attempts, overlap rejections, identity hash and bounds.

No current official boundary correctness, fresh OSM extraction, complete city coverage,
or explicit upstream data license is claimed. OSM map tiles are independent.
