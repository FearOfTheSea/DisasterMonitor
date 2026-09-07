# Frontend design

The workspace uses a map-first layout with a midnight header, white surfaces, teal
controls, and locally served Inter fonts. Shared tokens live in `app/globals.css`;
feature styles remain with the feature, and breakpoint composition lives in
`app/responsive.css`. Inter is distributed under the license in `public/fonts`.

The initial map provides a Southeast Asian regional overview. Existing URL state
still restores the operator's location, zoom, display layers, and selected panel.
The shared runtime configuration owns the default view; the map feature re-exports
it for compatibility.

Incident search matches loaded locations, publishers, and source titles. It does
not request new provider data or change map records or coverage. Coverage status
and snapshot time remain visible; detailed provider notices expand independently.
Map layers open on demand and retain their selected state when the controls close.

A new assistant conversation starts with an empty transcript. Its starter questions
fill and focus the composer for editing; submitting remains an explicit action.
Source limitations remain available in the coverage disclosure and in actual
reports. The UI never substitutes illustrative records for unavailable data.

On phones, the incident feed scrolls within a bounded region so the map remains
reachable. Assistant, operations, and catalog panels occupy the available screen
below the header. Native disclosure controls, labeled search, keyboard focus rings,
and reduced-motion support apply across these surfaces.
