# Roadmap 2 actions reserved for the project owner

This is the fail-closed handoff for work an AI coding agent cannot legitimately
complete. Supporting code, templates, or commands do not make these gates pass.

## Baseline and release authority

- Confirm the intended Stage-3 starting SHA (`41bcc770014...` was local `HEAD` and
  `origin/main` when work began) and create the annotated baseline tag if desired. The
  agent did not tag, commit, push, branch, or alter release history.
- Choose a release ID only after corpus, labels, evaluator versions, configuration,
  code, model digest, and rights records are frozen. Behavior changes require a new ID.
- Review and commit intentionally. `AGENTS.md`, roadmap reports, local settings, data,
  experiments, and secrets remain excluded by repository policy.

## Data access and rights

- Obtain and safeguard an approved ReliefWeb app name, NASA FIRMS map key, and
  Copernicus GFM credentials. Register the GFM Vietnam AOIs. Never place them in Git.
- Retain the actual current terms/permissions and attribution requirements for NCHMF,
  FIRMS, GFM, ReliefWeb, each CAP authority, and every benchmark corpus.
- Approve category-specific retention by exact source and rights ID before deletion.
- Obtain xBD/xView2, DisasterInsight, or other benchmark assets only through authorized
  paths. Do not substitute fabricated or silently changed data.

## Human and external evaluation

- Obtain the required institutional ethics determination before recruitment. Approve
  consent, compensation, withdrawal, personal-data handling, and retention procedures.
- Pre-register and run MM-C with qualified operators/SMEs, TR-B with blinded SME
  ranking, and DS with blinded expert review. Freeze allocation, scenarios, endpoints,
  exclusion rules, and analysis before opening outcomes.
- Freeze and run the real licensed MM-A/MM-B corpus. Preserve immutable manifests,
  model digest/configuration, hardware/runtime metadata, results, and checksums.
- Recalculate study power from the registered endpoint/effect assumptions. The
  roadmap's participant ranges are planning recommendations, not completed evidence.

## Deployment and supervised pilot

- Provide a trusted reverse proxy that strips client identity headers, injects the
  authenticated operator ID, terminates TLS, and manages secrets. Only then enable
  attributable operator actions.
- Select monitored hosting, encrypted backup storage, alert routing, maintenance owner,
  incident contacts, and final API/worker/provider SLOs.
- Repeat the 2026-08-13 disposable local backup/restore smoke in the owner-controlled
  deployment, including encrypted off-host storage and recovery-time/objective checks.
- Retain evidence for worker restart, provider outage, model outage, duplicate delivery,
  out-of-order replay, backup/restore, stale-data, and identity-forgery drills.
- Conduct the 30-day supervised pilot. Measure API availability separately from upstream
  provider availability and verify no lost evidence, silent queue loss, prohibited
  autonomous action, or untraceable release dependency.

## Current release blockers

Normative promotion remains blocked until the baseline-tag decision, rights evidence,
licensed external datasets, legitimate human evaluations, recovery drill, trusted
deployment identity, and supervised pilot are complete. Automated tests and local
Compose success are engineering evidence, not substitutes.
