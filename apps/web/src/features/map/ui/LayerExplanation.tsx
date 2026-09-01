import type { MapLayerDefinition } from '@/features/map/model/mapLayerRegistry';

type LayerExplanationProps = {
  layer: MapLayerDefinition;
  onClose: () => void;
  sourceDetail?: string;
  freshnessDetail?: string;
  attribution?: string;
};

export function LayerExplanation({
  layer,
  onClose,
  sourceDetail,
  freshnessDetail,
  attribution,
}: LayerExplanationProps) {
  const headingId = `layer-explanation-${layer.id}`;
  return (
    <aside
      className="layer-explanation"
      role="dialog"
      aria-modal="false"
      aria-labelledby={headingId}
    >
      <header>
        <div>
          <span>{layer.category}</span>
          <h3 id={headingId}>About {layer.label}</h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${layer.label} details`}
        >
          Close
        </button>
      </header>
      <p>{layer.purpose}</p>
      <dl>
        <div>
          <dt>Source / authority</dt>
          <dd>{sourceDetail ?? layer.sourceDescription}</dd>
        </div>
        <div>
          <dt>Freshness meaning</dt>
          <dd>{freshnessDetail ?? layer.freshnessSemantics}</dd>
        </div>
        <div>
          <dt>Confidence / status meaning</dt>
          <dd>{layer.authorityDescription}</dd>
        </div>
        {(attribution ?? layer.attribution) ? (
          <div>
            <dt>Attribution</dt>
            <dd>{attribution ?? layer.attribution}</dd>
          </div>
        ) : null}
      </dl>
      <div className="layer-explanation-limitations">
        <strong>Limitations</strong>
        <ul>
          {layer.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
