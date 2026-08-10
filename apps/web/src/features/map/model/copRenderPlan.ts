import type { CommonOperationalPicture, CopGeometry } from '@/shared/types/assistant';

export type CopAuthority =
  'official_source' | 'source_supplied' | 'analytical_generated';

export type CopStyleSemantics = {
  authorityLabel: string;
  patternLabel: 'solid' | 'dotted' | 'dashed';
  strokeColor: string;
  fillColor: string;
  lineDash: number[];
};

export type CopRenderFeature = {
  featureId: string;
  layerId: string;
  authority: CopAuthority;
  semanticKind: string;
  status: string;
  uncertainty: string;
  attribution: string;
  geometry: CopGeometry;
  style: CopStyleSemantics;
};

export function buildCopRenderPlan(cop: CommonOperationalPicture): CopRenderFeature[] {
  return cop.layers.flatMap((layer) =>
    layer.features.map((feature) => ({
      featureId: feature.feature_id,
      layerId: layer.layer_id,
      authority: feature.authority,
      semanticKind: feature.semantic_kind,
      status: feature.status,
      uncertainty: feature.uncertainty,
      attribution: feature.attribution,
      geometry: feature.geometry,
      style: copStyleSemantics(feature.authority),
    })),
  );
}

export function copStyleSemantics(authority: CopAuthority): CopStyleSemantics {
  if (authority === 'official_source') {
    return {
      authorityLabel: 'Official source',
      patternLabel: 'solid',
      strokeColor: '#155e75',
      fillColor: 'rgba(21, 94, 117, 0.10)',
      lineDash: [],
    };
  }
  if (authority === 'source_supplied') {
    return {
      authorityLabel: 'Source-supplied',
      patternLabel: 'dotted',
      strokeColor: '#166534',
      fillColor: 'rgba(22, 101, 52, 0.09)',
      lineDash: [2, 6],
    };
  }
  return {
    authorityLabel: 'Analytical · AI-generated',
    patternLabel: 'dashed',
    strokeColor: '#b45309',
    fillColor: 'rgba(180, 83, 9, 0.12)',
    lineDash: [10, 6],
  };
}
