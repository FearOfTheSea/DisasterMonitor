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

OpenStreetMap is used only for the basic base map. The current-earthquake
workflow has bounded JMA, USGS, and ReliefWeb source adapters; other live
disaster datasets remain unimplemented. The browser retains the conversation for
the current tab session; the API does not persist multi-user conversations.

## Backend request flow

```mermaid
sequenceDiagram
    participant Browser
    participant Route as FastAPI route
    participant UseCase as AnswerMapQuestion
    participant Report as CurrentDisasterReportService
    participant Events as JMA/USGS event ports
    participant Situation as JMA/ReliefWeb situation ports
    participant Port as LanguageModel port
    participant Adapter as OllamaQwenAdapter
    participant Model as Ollama/Qwen

    Browser->>Route: POST /api/v1/assistant
    Route->>UseCase: validated question + map view
    UseCase->>UseCase: deterministic classification
    alt current-disaster request
        UseCase->>Report: normalized query
        Report->>Events: bounded recent-event lookup
        Events-->>Report: normalized candidates + issues
        Report->>Report: rank event and reconcile evidence
        Report->>Situation: selected event lookup
        Situation-->>Report: normalized facts + issues
        Report-->>UseCase: deterministic source-backed report
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

The application layer depends on the `LanguageModel` protocol and provider-neutral DTOs. It does not import FastAPI, Ollama, `httpx`, or Pydantic. `main.create_app` is the composition root that selects the concrete adapter.

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
```

`OllamaQwenAdapter` implements the model port. JMA, USGS, and ReliefWeb adapters
implement the disaster ports. Tests inject deterministic implementations. No
speculative ports exist for weather, satellite, geocoding, or remote providers.

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

`create_app(settings, model)` accepts an optional model for tests. Production construction builds `Settings`, then `OllamaQwenAdapter`, then `AnswerMapQuestion`. Backend tests use a fake model and `httpx.ASGITransport`; adapter tests use `httpx.MockTransport`. Frontend tests cover the client, session store, assistant states, and form submission. The Playwright system test starts the real Next.js UI against a FastAPI app with a fake model.

## Adding a future external-data capability

1. Define the smallest application DTO and port needed by a user-facing use case.
2. Validate and normalize its input in the application layer.
3. Implement the provider-specific HTTP or SDK behavior in `infrastructure`.
4. Construct the adapter explicitly in the composition root.
5. Add deterministic unit and adapter tests before wiring a UI control.
6. Keep unavailable or unconfigured data visibly unavailable; do not return placeholder success.

If the capability needs map overlays, add a focused map operation to the existing adapter only after the application feature uses it. Do not turn `OpenLayersMapAdapter` into a generic mapping framework.
