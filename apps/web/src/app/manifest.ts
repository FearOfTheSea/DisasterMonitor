import type { MetadataRoute } from 'next';

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Disaster Monitor',
    short_name: 'Disaster Monitor',
    description: 'Local-first disaster monitoring and geospatial operations.',
    start_url: '/',
    display: 'standalone',
    background_color: '#071118',
    theme_color: '#071118',
  };
}
