# JMA tsunami status

Official JMA tsunami bulletin status for a selected Japan earthquake. The bounded JSON
feed needs no configuration, but the event must have a JMA identifier. Bulletin labels
and timestamps become attributed status facts and exact comparable JMA IDs establish
association. No matching bulletin is a successful neutral empty result; it is not a
claim of no tsunami impact. Connectivity, malformed payloads, and unsupported shapes
are provider issues. Latency, accuracy, and availability guarantees are unknown. Tests:
JMA tsunami adapter and neutral-absence regression. Extensions must not infer impact
from bulletin absence.
