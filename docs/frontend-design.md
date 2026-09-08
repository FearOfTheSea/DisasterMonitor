# Frontend design

The workspace uses an approachable map-first layout with a quiet white header, cool
map surfaces, deep navy type, teal controls, and locally served Inter fonts. Shared
tokens live in `app/globals.css`; feature styles remain with the feature, and
breakpoint composition lives in `app/responsive.css`. Inter is distributed under the
license in `public/fonts`.

The default experience prioritizes recent events, associated country or territory,
source location, relative time, and map context. Every Active Incidents card uses the
structured country association as its heading. A meaningful provider location remains
secondary context, while technical acquisition identifiers stay in source details.
Provider tiers, association basis, identifiers, exact source timestamps, coverage
limitations, map coordinates, and other specialist metadata remain available through
labelled native disclosures. Search, sources, saved monitoring, and the assistant open
one at a time in an overlay drawer so the map retains its context.

The initial map provides a Southeast Asian regional overview. Existing URL state
still restores the operator's location, zoom, display layers, and selected panel.
The shared runtime configuration owns the default view; the map feature re-exports
it for compatibility.

Incident search matches loaded country names and codes, source locations, publishers,
and source titles. It does not request new provider data or change map records or
coverage. Coverage status and snapshot time remain visible; detailed provider notices
expand independently. Map layers open on demand and retain their selected state when
the controls close.

A new assistant conversation starts with an empty transcript. Its starter questions
fill and focus the composer for editing; submitting remains an explicit action.
Source limitations remain available in the coverage disclosure and in actual
reports. Assistant responses use the same open white surfaces, navy hierarchy, teal
accents, and restrained dividers as the incident rail. User questions remain compact,
while source-backed reports use readable body text, spaced sections, and wrapping
metadata so long identifiers and URLs cannot force horizontal scrolling. The UI never
substitutes illustrative records for unavailable data.

On phones, the compact header and persistent Explore, Ask, Saved, and Sources
navigation keep the primary paths reachable. The incident feed scrolls within a
bounded region, the selected event summary remains above the navigation, and the map
stays reachable below the feed. Assistant, operations, and catalog panels occupy the
available screen below the header. Native disclosure controls, labelled search,
keyboard focus rings, and reduced-motion support apply across these surfaces.
