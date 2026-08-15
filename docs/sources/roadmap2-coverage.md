# Roadmap 2 source coverage

Roadmap 2 extends the executable source registry through the existing authority,
country, hazard, host, and configuration boundaries. It does not imply worldwide
coverage and does not turn analytical detections into official incident facts.

| Source | Executable coverage | Evidence type | Configuration | Authority limit |
|---|---|---|---|---|
| NCHMF RSS | Vietnam flood, landslide/flash-flood, tropical cyclone | Event discovery and official warning headline | None | National warning authority; a headline does not establish impacts |
| NASA FIRMS area API | Wildfire for packaged country bounds | Satellite active-fire observation | Reviewed map key | Scientific observation; not an incident declaration |
| Copernicus GFM notifications | Vietnam flood AOIs registered to the account | Analytical satellite flood-product availability | Access token and user ID | Estimated analytical product; not a national warning |
| Generic CAP 1.2 adapter | Only an explicitly constructed and registered country/hazard authority | Public, actual CAP alert | Reviewed URL, hosts, publisher, source and rights ID | Never auto-registered; non-public/test alerts are rejected |
| ReliefWeb | Configured supported hazards/countries | Supplementary humanitarian reporting | Pre-approved app name | Aggregator, not proof of national warning authority |

Every successful bounded HTTP response can be captured before parsing. The
content-addressed blob, checksum, request fingerprint, source ID, rights ID, and
retrieval time form an immutable `source_snapshot`. Normalized facts carry the exact
snapshot ID. A canonical world state is written only if every normalized fact has
that durable lineage; otherwise the response remains request-scoped and says so.

Provider URLs remain HTTPS and registry-host constrained, response sizes are bounded,
XML uses `defusedxml`, and credentials are omitted from request identities. Missing
credentials produce explicit unavailable coverage.

Source rights IDs are references for reviewed terms, not a claim that legal review is
complete. The owner must retain the evidence listed in
[project-owner-actions.md](../project-owner-actions.md).
