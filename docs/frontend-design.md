# Frontend design

Disaster Monitor is a desktop-first Earth observatory. The 64px header leads to
Explore, Saved, Sources, Tools, Help, the command palette, and the assistant. Dark
tokens in `app/globals.css` define the ocean, land, panels, text, dividers, and mint
interactive accent. Feature styling stays with its feature; `app/observatory.css`
owns the desktop composition. Inter is served locally under `public/fonts`.

Explore keeps the incident rail and OpenLayers map mounted while a user visits other
workspaces. At 1440px and wider, the rail is 352px and the event or assistant reading
pane is 440px. At 1200–1439px, they are 304px and 400px. Below 1200px, opening a
reading pane hides the incident rail until the user returns to events. The map gets
the remaining width and remains interactive. Incident search filters loaded records;
it does not run worldwide discovery. List rows show hazard, place, source location,
activity state, and time. Coverage and excluded observations remain available in a
disclosure. Cached records show absolute event time.

The default geographic view is global and fits the available map rectangle. The
locally bundled Natural Earth atlas shows land, borders, country labels, marine
labels, and graticules. It begins with generalized geography and loads finer country
geometry at detailed zoom. Streets is an explicit OpenStreetMap alternative;
satellite imagery remains an independent source-dated overlay. Atlas asset provenance
is recorded in `public/atlas/README.md`. The map does not generate geographic or
impact geometry from visual design. Existing URLs with explicit position or zoom
take precedence over the default view.

Selecting a list row or map marker opens an event reading pane without invoking the
assistant. Its Overview is built from recorded incident fields, the Evidence tab
retains source categories and provenance, and Timeline shows only recorded times.
An explicit action fills the assistant draft for editing. Assistant requests preserve
the draft on failure and show elapsed request time without invented progress. Ground
view uses a wide inspection workspace with its existing radar and optical controls,
comparison modes, and imagery limitations.

Saved contains Watches, Bookmarks, and Activity. Sources is a read-only directory
with search, hazard and role filters, and expandable provenance; configuration
availability does not imply live provider health. Tools contains Field reports,
Workspace notes and checklists, Source health, Evidence history, and Maintenance.
Workspace notes remain separate from evidence. Help and the command palette are
dialogs; nonmodal reading panes do not trap focus. Focus indicators, keyboard
selection paths, native disclosures, and reduced-motion styling apply throughout.

Application-level URL parameters hold the destination, subsection, and active
Explore pane. Map URL parameters independently hold position, region, layers,
selection, time window, satellite state, and basemap. Each serializer preserves the
other's parameters and unrelated query values. Browser Back and Forward restore
both groups of state. The assistant conversation and map selection live above pane
visibility so changing workspace does not start duplicate requests or recreate the
map.
