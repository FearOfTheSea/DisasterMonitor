import type { Metadata } from 'next';
import { PwaRegistration } from './PwaRegistration';
import './globals.css';
import '../features/map/ui/map.css';
import '../features/map/ui/mapObservatory.css';
import '../features/incidents/ui/activeIncidents.css';
import '../features/incidents/ui/activeIncidentsCompact.css';
import '../features/incidents/ui/selectedEvent.css';
import '../features/incidents/ui/accessibleIncident.css';
import '../features/incidents/ui/coverageStatus.css';
import '../features/incidents/ui/activeIncidentsControls.css';
import '../features/incidents/ui/provisionalIncidents.css';
import '../features/map/ui/mapLegends.css';
import './panels.css';
import '../features/sources/ui/sourceCatalog.css';
import '../features/commands/ui/commandPalette.css';
import '../features/help/ui/workspaceHelp.css';
import '../features/assistant/ui/assistant.css';
import '../features/assistant/ui/assistantEvidence.css';
import '../features/operations/ui/operations.css';
import '../features/imagery/ui/groundImagery.css';
import '../shared/ui/dataAge.css';
import './responsive.css';
import './observatory.css';

export const metadata: Metadata = {
  title: 'Disaster Monitor',
  description: 'A local-first disaster-monitoring and geospatial operations workspace.',
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <PwaRegistration />
        {children}
      </body>
    </html>
  );
}
