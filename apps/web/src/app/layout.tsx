import type { Metadata } from 'next';
import './globals.css';
import '../features/map/ui/map.css';
import '../features/incidents/ui/activeIncidents.css';
import '../features/map/ui/mapLegends.css';
import './panels.css';
import '../features/sources/ui/sourceCatalog.css';
import '../features/commands/ui/commandPalette.css';
import '../features/assistant/ui/assistant.css';
import '../features/operations/ui/operations.css';
import './responsive.css';

export const metadata: Metadata = {
  title: 'Disaster Monitor',
  description: 'A local-first disaster-monitoring and geospatial operations workspace.',
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
