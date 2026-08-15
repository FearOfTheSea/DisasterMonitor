# External and generated data boundary

Only this README is tracked. Every other path under `data/` is ignored and must stay
outside Git.

Use the following categories:

- `disasteragentbench/`: locked episode manifests, immutable source snapshots,
  separated hidden labels, and source-rights records.
- `multimodal/`: licensed image assets and locked multimodal release manifests.
- `operator-study/`, `sme-study/`, `ds-expert-study/`: deidentified study artifacts;
  never store names, email addresses, compensation details, or consent records here.
- `raw/`: source payload staging.
- `experiments/`: generated experiment identities and evaluator outputs.
- `replay/`: generated operational and canonical replay results.

Every staged payload must have a SHA-256 in its controlling manifest. Third-party data
must not be copied into the repository. Hidden release labels are evaluator-only and
must never be imported by production application code.
