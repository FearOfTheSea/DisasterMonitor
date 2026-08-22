import type { Metadata } from 'next';
import './globals.css';

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
