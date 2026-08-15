# North Star evaluation and reproducibility

Roadmap 2 adds DisasterAgentBench (DAB) as a release-evaluation subsystem. It is not a
source provider and production application code cannot load its hidden labels.

## Tracked and external boundaries

Tracked code contains manifest validators, canonical hashing, replay logic, scripts,
small synthetic adversarial fixtures, example manifests, and evaluator tests. Licensed
or rights-sensitive data, source payloads, hidden labels, study records, experiment
outputs, and replay outputs remain under ignored `data/` paths described in
[`data/README.md`](../../data/README.md).

The canonical manifest hash is SHA-256 over UTF-8 JSON with sorted keys, no
insignificant whitespace, and the top-level `manifest_sha256` field excluded. File
hashes use the `sha256:<64 lowercase hex>` representation. Validators resolve every
relative path inside the staged root and fail closed on missing files, root escape,
checksum change, absent rights records, duplicate identities, naive timestamps, empty
episodes, or unsupported hazards.

## Workflow

Prepare an owner-curated selection without downloading or redistributing data:

```powershell
uv run --directory apps/api python scripts/prepare_disaster_agent_bench.py `
  --staged-root ../../data/disasteragentbench `
  --selection-file ../../data/disasteragentbench/selection.json `
  --output-manifest ../../data/disasteragentbench/locked-release-manifest.json
```

Verify every snapshot, hidden-label file, rights record, and checksum:

```powershell
uv run --directory apps/api python scripts/verify_release_manifest.py `
  --manifest ../../data/disasteragentbench/locked-release-manifest.json
```

Run the integrity and deterministic-replay gate:

```powershell
uv run --directory apps/api python scripts/run_disaster_agent_bench.py `
  --manifest ../../data/disasteragentbench/locked-release-manifest.json `
  --output ../../data/experiments/dab-release-result.json
```

The command intentionally exits with code 2 after a successful integrity/replay run
unless `--integrity-only` is supplied. Integrity is not normative Stage-3 promotion:
EW still needs independent hidden outcomes, TR-B still needs blinded SME rankings,
DS-A/B still need blinded expert review, and MM keeps its existing external release
gates. `--integrity-only` is for corpus preparation and CI checks; it must not be used
to label a release promoted.

Replay an episode in either frozen ordering:

```powershell
uv run --directory apps/api python scripts/replay_ingestion.py `
  --episode ../../data/disasteragentbench/episodes/<episode-id> `
  --mode original-ingestion-order `
  --output ../../data/replay/<episode-id>/original.json
```

Use `canonical-effective-time` for the reconciliation ordering. Both modes must produce
the same final source-set and canonical-effective-state hashes even when an older
revision was retrieved after a newer one.

Record the actual commit, dirty paths, lockfile hash, runtime, command, evaluator, and
optional manifest identity:

```powershell
uv run --directory apps/api python scripts/record_experiment_baseline.py `
  --output ../../data/experiments/stage3-baseline.json `
  --require-clean
```

Release records must be produced from a clean tree. Development records may omit
`--require-clean`, but their dirty paths stay explicit and cannot support a frozen
release claim.
