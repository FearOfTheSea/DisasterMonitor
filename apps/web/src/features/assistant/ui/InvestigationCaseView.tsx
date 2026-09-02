import type { InvestigationCase } from '@/shared/types/assistant';

type InvestigationCaseViewProps = {
  investigationCase: InvestigationCase;
};

function hazardLabel(disaster: string): string {
  return disaster
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function elapsedLabel(seconds: number): string {
  if (seconds < 3600) return 'less than 1 hour';
  const hours = Math.round(seconds / 3600);
  return `${hours} ${hours === 1 ? 'hour' : 'hours'}`;
}

export function InvestigationCaseView({
  investigationCase,
}: InvestigationCaseViewProps) {
  return (
    <section className="investigation-case" aria-label="Two-hazard investigation">
      <header>
        <h3>Two-hazard investigation</h3>
        <p>
          {investigationCase.country.country_name} (
          {investigationCase.country.country_code}){' · '}
          <strong>
            {investigationCase.partial
              ? 'Partial investigation'
              : 'Completed investigation'}
          </strong>
        </p>
      </header>

      <div className="investigation-case-branches">
        {investigationCase.targets.map((target) => (
          <article
            key={target.target_id}
            aria-label={`${hazardLabel(target.disaster)} branch`}
          >
            <h4>{hazardLabel(target.disaster)}</h4>
            <p>
              Status: <strong>{target.status.replaceAll('_', ' ')}</strong>
              {target.partial ? ' · Partial/degraded evidence' : ''}
            </p>
            {target.selected_event && (
              <p>
                Selected event: {target.selected_event.location} ·{' '}
                {new Date(target.selected_event.event_time).toLocaleString()}
              </p>
            )}
            {target.sections.map((section) => (
              <section key={`${target.target_id}:${section.title}`}>
                <h5>{section.title}</h5>
                <p>{section.content}</p>
              </section>
            ))}
            {target.warnings.length > 0 && (
              <div role="status">
                <h5>Warnings</h5>
                {target.warnings.map((warning) => (
                  <p key={`${target.target_id}:${warning}`}>{warning}</p>
                ))}
              </div>
            )}
            {target.sources.length > 0 && (
              <div>
                <h5>Sources</h5>
                {target.sources.map((source) => (
                  <a
                    key={`${target.target_id}:${source.source_id}`}
                    href={source.canonical_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {source.publisher}: {source.title}
                  </a>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>

      <section className="investigation-case-assessment">
        <h4>Cross-hazard assessment</h4>
        <p>
          Status:{' '}
          <strong>
            {investigationCase.cross_hazard_assessment.status.replaceAll('_', ' ')}
          </strong>
        </p>
        <p>{investigationCase.cross_hazard_assessment.summary}</p>
        <p>{investigationCase.cross_hazard_assessment.limitation}</p>
        {investigationCase.correlations.map((correlation) => (
          <article key={correlation.correlation_id}>
            <strong>Spatiotemporal association</strong>
            <p>{correlation.summary}</p>
            <small>
              Distance: {correlation.distance_km} km · Time difference:{' '}
              {elapsedLabel(correlation.time_delta_seconds)}
            </small>
            <p>{correlation.limitation}</p>
          </article>
        ))}
      </section>
    </section>
  );
}
