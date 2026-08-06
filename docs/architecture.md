# Architecture

## System context

```mermaid
flowchart LR
    browser["Browser"] --> web["Next.js web app"]
    web --> api["FastAPI API"]
    api --> ollama["Local Ollama / Qwen"]
    api --> jma["JMA JSON feeds"]
    api --> usgs["USGS GeoJSON"]
    api --> reliefweb["ReliefWeb JSON"]
    web --> osm["OpenStreetMap tiles"]
```

OpenStreetMap is used only for the basic base map. The current-disaster workflow
normalizes a typed hazard and country before provider access. Japan earthquake
adapters remain the current live scope while capability routing is being expanded;
other live disaster datasets remain unimplemented. The browser retains the conversation for
the current tab session; the API does not persist multi-user conversations.

## Backend request flow

```mermaid
sequenceDiagram
    participant Browser
    participant Route as FastAPI route
    participant UseCase as AnswerMapQuestion
    participant Report as CurrentDisasterReportService
    participant Registry as ProviderRegistry
    participant Events as JMA/USGS event ports
    participant Situation as JMA/ReliefWeb situation ports
    participant Port as LanguageModel port
    participant Adapter as OllamaQwenAdapter
    participant Model as Ollama/Qwen

    Browser->>Route: POST /api/v1/assistant
    Route->>UseCase: validated question + map view
    UseCase->>UseCase: parse hazard + country once
    alt current-disaster request
        UseCase->>Report: normalized query
        Report->>Registry: select event providers by capability
        alt no event capability
            Report-->>UseCase: coverage-unavailable report
        else event capability exists
        Report->>Events: bounded recent-event lookup
        Events-->>Report: normalized candidates + issues
        Report->>Report: rank event and reconcile evidence
        Report->>Situation: selected event lookup
        Situation-->>Report: normalized facts + issues
        Report-->>UseCase: deterministic source-backed report
        end
    else ordinary request
    UseCase->>UseCase: normalize and prepare deterministic messages
    UseCase->>Port: generate(ModelRequest)
    Port->>Adapter: provider-neutral call
    Adapter->>Model: POST /api/chat
    Model-->>Adapter: provider response
    Adapter-->>UseCase: ModelResponse
    end
    UseCase-->>Route: AssistantAnswer
    Route-->>Browser: stable JSON response
```

The application layer depends on the `LanguageModel`, disaster-information, and
country-catalog ports plus provider-neutral DTOs. Stable disaster facts live in
`domain/disaster.py`; workflow results and `DisasterQuery` remain in the
application layer. `DisasterQuery` contains one typed `Hazard` and one canonical
`Country`, so country name and ISO code cannot diverge. The application does not
import FastAPI, Ollama, `httpx`, or Pydantic. Composition selects concrete adapters.

## Frontend boundaries

- `AssistantClient` owns HTTP transport and response-shape checks.
- `useAssistantConversation` owns the user-message / assistant-response workflow, status, and errors.
- `SessionConversationStore` owns browser `sessionStorage` serialization.
- `OpenLayersMapAdapter` owns map construction, view conversion, and cleanup.
- `AssistantPanel` and `DisasterMap` render state and emit user actions.
- `app/page.tsx` composes the map, assistant drawer, and current map-view context.

React components do not call Ollama, manipulate browser storage directly, or construct arbitrary OpenLayers layers beyond the adapter boundary.

## Ports and adapters

The application uses these meaningful ports:

```text
LanguageModel
  generate(ModelRequest) -> ModelResponse
  check_readiness() -> ModelReadiness

DisasterEventProvider
  find_recent_events(DisasterQuery, now) -> ProviderBatch[DisasterEvent]

SituationReportProvider
  get_situation_reports(DisasterEvent, DisasterQuery, now) -> ProviderBatch[SituationReport]

CountryCatalog
  find_mentions(text) -> tuple[Country, ...]
  contains(Country, latitude, longitude) -> bool
```

`OllamaQwenAdapter` implements the model port. JMA, USGS, and ReliefWeb adapters
implement the disaster ports. Tests inject deterministic implementations. No
speculative ports exist for weather, satellite, geocoding, or remote providers.

`ProviderRegistry` holds registrations with role, typed hazard, country scope,
configuration requirements, and optional selected-event eligibility. `None` country
scope means global. The fan-out composites invoke only the registry selection and
continue to isolate individual adapter failures. A recognized query with no event
capability returns `current_disaster_coverage_unavailable` before situation lookup
or language-model generation.

Provider fan-out returns raw normalized records. Application-owned event policies
decide physical-event equivalence, clustering, ranking, sequence relationships, and
ambiguity. `EarthquakeEventPolicy` preserves magnitude, intensity, significance,
recency, distance, and aftershock behavior. `DefaultEventPolicy` merges only strong
shared identifiers, prefers newer matching events, and marks similarly recent
independent events ambiguous.

`CurrentDisasterReportService` orchestrates only the workflow. `EvidenceReconciler`
performs correlation and fact precedence, `DisasterReportRenderer` renders normalized
evidence, and `report_profiles.py` supplies earthquake-specific or generic section
configuration. Generic rendering reads the query hazard/country and selected event;
it contains no unconditional Japan or earthquake wording.

## Dependency direction

```mermaid
flowchart TB
    http["HTTP presentation"] --> app["Application use case"]
    app --> port["LanguageModel port"]
    app --> domain["Domain models and errors"]
    infra["Infrastructure adapter"] -. implements .-> port
    root["Composition root"] --> infra
    root --> app
```

Transport schemas and Ollama payloads remain at the edges. The use case prepares a deterministic system prompt that prevents claims about unavailable live data and strips common hidden-reasoning wrappers from model output.

## Composition and testing

`create_app` accepts optional adapters for tests. Production construction builds
`Settings`, the packaged `StaticCountryCatalog`, `DisasterQueryParser`, source
providers, `OllamaQwenAdapter`, and `AnswerMapQuestion`. Backend tests use a fake
model and `httpx.ASGITransport`; adapter tests use `httpx.MockTransport`.

The versioned MVP country resource currently recognizes Japan, Vietnam, and
Venezuela by canonical English name, ISO alpha-2/alpha-3 code, and declared exact
aliases. Its query rectangles and simplified polygons are Natural Earth-derived
geographic approximations, not legal borders or maritime claims. Fixed calendar
offsets are used for these three countries,
which do not use seasonal daylight-saving transitions.

## Adding a future external-data capability

1. Define the smallest application DTO and port needed by a user-facing use case.
2. Validate and normalize its input in the application layer.
3. Implement the provider-specific HTTP or SDK behavior in `infrastructure`.
4. Construct the adapter explicitly in the composition root.
5. Add deterministic unit and adapter tests before wiring a UI control.
6. Keep unavailable or unconfigured data visibly unavailable; do not return placeholder success.

If the capability needs map overlays, add a focused map operation to the existing adapter only after the application feature uses it. Do not turn `OpenLayersMapAdapter` into a generic mapping framework.
