# Local assistant event quality

The local assistant first interprets a user's bounded disaster request, then asks
configured providers for candidate records. Source records, geography, event identity,
and place matching decide what the answer can claim. A model interpretation cannot
create a verified event or impact.

## Live regression cases

`evaluation/local_assistant_cases.v1.json` records independently checked event IDs,
source links, natural questions, and named places. Its five cases include three
initial events and two unrelated repeat-validation events. Run the scorer against
the running development backend without starting another Docker stack:

```bash
uv run --directory apps/api python -m disaster_monitor.evaluation.local_assistant_e2e \
  ../../evaluation/local_assistant_cases.v1.json \
  --api-url http://127.0.0.1:8002 --output /tmp/local-assistant-e2e.json
```

`verified_event` requires the expected event ID, a source URL bearing that ID, and
the requested place in the selected event's location. `honest_place_gap` means a
country event was found but the named place was not verified; it remains a partial
result and fails the recall gate. `wrong_event`, `missed_event`,
`unattributed_event`, `unattributed_place_gap`, and
`unverified_place_attribution`, and `wrong_place_impact` fail the gate. Provider
outages and truncated acquisition are visible through `event_issue_codes` and
`event_scan_complete` in the investigation response. Do not interpret an incomplete
scan as evidence that no matching event exists.

On 2026-09-24, the final port 8002 run scored all five cases as `verified_event`:
the Nikolski and Uken earthquakes, the Nghệ An and Cotabato floods, and Krakatau.
Each selected the independently checked event ID, named place, and source URL.
The earlier baseline had missed or misattributed events in these cases. The Uken
question initially selected a merged GDACS record with only "Japan" as its
location; the final run selected the USGS observation that names Uken. The Nghệ An
question initially returned only a country candidate; the final run linked the
flood to the province through a GDACS report headline for episode 6.

This five-case gate tests event selection, place association, source links, and
known cross-region impact contamination in the Nghệ An answer. Facts with an
explicit reported location outside the requested place are omitted from a
place-specific report. This does not establish complete provider coverage or
verify every impact figure in a report. Nikolski, Nghệ An, and Cotabato still
reported incomplete scans. The Krakatau request reported a rejected provider
configuration. Preserve those issue
codes in the response and do not turn a partial scan into a claim of exhaustive
coverage.

## Follow-up improvements

1. Expand region-level event association beyond the bounded GDACS flood report
   headline lookup. Extend typed geographic scope to other situation providers;
   facts without a reported location still require source-specific review before
   claiming they apply to a named place.
2. Improve acquisition completeness for large country bounds, particularly
   cross-dateline countries and USGS's per-request cap. Keep provider budgets and
   `scan_complete` explicit.
3. Add replay snapshots for the live cases and unrelated cases for each future
   change, then measure event recall, wrong-event rate, place attribution, and
   source-link correctness separately by hazard and provider.
4. Review WVAR 403 failures with the upstream provider. Keep GDACS as separately
   attributed corroboration; do not imply that a blocked WVAR fetch verified an
   eruption.

The standalone backend on port 8002 has degraded durable-monitoring readiness, so
these results validate the live request path rather than scheduler continuity.
