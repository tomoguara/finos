# Spec Delta

## Purpose

Defines the compiled support graph that runs the supervisor and exactly one specialist per query, the `ask` helper every entry point uses to invoke it, and the diagram text that shows its wiring.

## ADDED Requirements

### Requirement: The graph routes each query to exactly one specialist
The compiled graph SHALL start at the supervisor node, follow one conditional edge to exactly one of `policy_agent`, `account_agent`, or `escalation_agent`, and end after that specialist. The conditional edge SHALL declare its three possible targets explicitly. Specialists SHALL be wired without changes to their behavior.

#### Scenario: Each intent reaches its specialist
- **WHEN** the supervisor classifies a query as each intent in turn
- **THEN** only the matching specialist runs, and the graph ends after it

#### Scenario: Declared targets
- **WHEN** the compiled graph's structure is inspected
- **THEN** the supervisor node has exactly three outgoing conditional edges, to the three specialists, and each specialist has one edge to the end

### Requirement: Building the graph is free of side effects
Building the graph SHALL load settings before anything else, so tracing settings apply before any traced call. It SHALL make no model call, open or build no vector index, and make no network request. Each call SHALL build a new compiled graph; nothing SHALL be cached between calls.

#### Scenario: No model or index at build time
- **WHEN** the graph is built with fake models that fail if invoked, and `data/chroma/` absent
- **THEN** building succeeds, no model is invoked, and `data/chroma/` is not created

#### Scenario: Settings load first
- **WHEN** the graph is built
- **THEN** settings have been loaded before any node is registered

#### Scenario: Fresh graph per call
- **WHEN** the graph is built twice
- **THEN** the two results are distinct objects

### Requirement: The ask helper returns a complete state
The `ask` helper SHALL invoke a compiled graph with the initial state for the query and return the final `SupportState`. It SHALL NOT validate the query. Exceptions raised inside the graph SHALL propagate out of `ask`, and no partial state SHALL be returned.

#### Scenario: Policy route
- **WHEN** `ask` runs a query the supervisor classifies as `policy`
- **THEN** the result has all five fields, `intent` is `policy`, and `context` and `retrieved_sources` come from the policy agent

#### Scenario: Account and escalation routes
- **WHEN** `ask` runs queries classified as `account_status` and as `escalation`
- **THEN** each result has empty `context` and `retrieved_sources`, and the escalation response ends with the support contact block

#### Scenario: Every route passes strict validation
- **WHEN** the result of `ask` for each intent is validated strictly with the policy corpus filenames as known sources
- **THEN** no problems are returned

#### Scenario: Exceptions propagate
- **WHEN** a model raises a connection error during `ask`
- **THEN** `ask` raises that error rather than returning a state

### Requirement: The graph's wiring can be rendered as diagram text
The system SHALL render the compiled graph's structure as PlantUML state-diagram text by default:
- a start transition to the supervisor node;
- a dashed transition from the supervisor to each specialist, labeled with the intent that selects it;
- a transition from each specialist to the end.

It SHALL also render Mermaid text on request. Rendering SHALL make no model call and require no dependency beyond those already locked.

#### Scenario: PlantUML text
- **WHEN** the graph is rendered as PlantUML
- **THEN** the text starts with `@startuml`, ends with `@enduml`, contains `[*] --> classify_intent`, dashed transitions to `policy_agent`, `account_agent`, and `escalation_agent` labeled `policy`, `account_status`, and `escalation`, and a transition from each specialist to `[*]`

#### Scenario: Mermaid text
- **WHEN** the graph is rendered as Mermaid
- **THEN** the text names all four nodes
