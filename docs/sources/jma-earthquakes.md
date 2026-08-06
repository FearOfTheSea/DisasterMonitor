# JMA rolling earthquakes

Official JMA event discovery and scientific verification for Japan earthquakes. The
adapter reads the bounded rolling JSON list without configuration and translates JMA
ID, time, location, magnitude, intensity, depth, coordinates, timestamps, and authority
into domain records. Query time and packaged Japan geography are enforced. JMA IDs stay
namespaced; cross-source clustering uses application-owned time, distance, and
magnitude rules. Connectivity, malformed payload, and empty-result diagnostics remain
explicit. Feed retention, latency, accuracy, and availability guarantees are unknown.
Tests: `tests/integration/test_disaster_adapters.py` and event policy/regression suites.
Extensions must preserve IDs and add only normalized typed fields.
