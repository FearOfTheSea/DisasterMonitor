import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Disaster Monitor',
  description: 'A local-first map and disaster-monitoring assistant.',
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
