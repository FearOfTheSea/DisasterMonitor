# MeteoAlarm warnings

DisasterMonitor reads public MeteoAlarm Atom feeds only for country feed names that an operator explicitly configures with `METEOALARM_COUNTRY_FEEDS`. Each linked CAP 1.2 document remains an official warning artifact from its named national meteorological service. Original links, languages, event codes, lifecycle references, areas, and validity times are retained.

The adapter is bounded by response-byte and record limits, rejects redirects and links outside the approved MeteoAlarm host, and reports partial retrieval separately from a successful empty feed. It does not turn a warning into a physical incident or infer missing geometry.

Attribution: Source: MeteoAlarm and the issuing national meteorological service. Feed and message reuse remains subject to MeteoAlarm and issuer-specific terms.
