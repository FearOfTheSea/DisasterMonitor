import type { DisasterType } from '@/features/incidents/model/activeIncidents';

export function DisasterIcon({ disaster }: { disaster: DisasterType }) {
  return (
    <svg
      className={`disaster-icon disaster-icon-${disaster}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {disaster === 'earthquake' ? (
        <path d="M2.5 13h4l1.8-6 3.4 11 2.3-8 1.8 3H21.5" />
      ) : null}
      {disaster === 'flood' ? (
        <>
          <path d="M2.5 8.5c2.3-2 4.7-2 7 0s4.7 2 7 0 4.7-2 7 0" />
          <path d="M2.5 14.5c2.3-2 4.7-2 7 0s4.7 2 7 0 4.7-2 7 0" />
          <path d="M2.5 20c2.3-2 4.7-2 7 0s4.7 2 7 0 4.7-2 7 0" />
        </>
      ) : null}
      {disaster === 'wildfire' ? (
        <path d="M13.5 2.5c.7 4-2.8 5.2-1.7 8.3.7-1.2 1.9-2 3.3-2.4 2.6 2.3 4 4.6 3.5 7.2-.6 3.3-3.3 5.9-6.8 5.9s-6.4-2.7-6.4-6.2c0-2.7 1.5-5 4.6-7.1-.2 2.1.4 3.5 1.6 4.2-.2-3.5.6-6.8 1.9-9.9Z" />
      ) : null}
      {disaster === 'landslide' ? (
        <>
          <path d="m2.5 19 6.7-12 4.1 7 2.1-3.5L21.5 19Z" />
          <path d="m12.2 8.2 1.8-3M15.4 8.4l2.5-1M16.6 11.2l2.8.2" />
        </>
      ) : null}
      {disaster === 'tropical_cyclone' ? (
        <>
          <path d="M19.8 7.5A8.3 8.3 0 0 0 5 8c1.7-1 4.3-1.2 6.2.3 1 .8 1.5 2.2 1.2 3.5" />
          <path d="M4.2 16.5A8.3 8.3 0 0 0 19 16c-1.7 1-4.3 1.2-6.2-.3-1-.8-1.5-2.2-1.2-3.5" />
          <circle cx="12" cy="12" r="1.5" />
        </>
      ) : null}
      {disaster === 'volcanic_eruption' ? (
        <>
          <path d="m4 20 5.6-11h4.8L20 20Z" />
          <path d="m9.6 9 2.4 3 2.4-3M8.5 5.5 7 3.5M12 5V2M15.5 5.5 17 3.5" />
        </>
      ) : null}
    </svg>
  );
}
