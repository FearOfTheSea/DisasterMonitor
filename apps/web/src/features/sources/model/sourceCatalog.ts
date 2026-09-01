export type SourceAvailability = 'available' | 'unconfigured' | 'maintained_only';

export type SourceOperationalState = {
  registered: boolean;
  configured: boolean;
  availability: SourceAvailability;
  availability_detail: string;
  provider_tier: 'primary' | 'secondary' | null;
  execution_roles: string[];
};

export type SourceCatalogItem = {
  source_id: string;
  provider: string;
  publisher: string;
  authority: string;
  information_roles: string[];
  supported_disasters: string[];
  geographic_scopes: string[];
  country_codes: string[] | null;
  coverage_description: string;
  documentation_path: string | null;
  freshness_semantics: string;
  stale_threshold_seconds: number | null;
  attribution: string;
  limitations: string[];
  operational_state: SourceOperationalState;
};

export type SourceCatalogSnapshot = {
  catalog_version: string;
  sources: SourceCatalogItem[];
};
