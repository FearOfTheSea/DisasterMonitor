/** The workspace owns storage and navigation; imagery owns the retained selection. */
export type GroundImageryRetention = {
  read: (incidentId: string) => { requestId: string; artifactId?: string } | undefined;
  saveRequest: (incidentId: string, requestId: string) => void;
  saveArtifact: (incidentId: string, requestId: string, artifactId: string) => void;
  clear: (incidentId: string) => void;
};
