# Spec Delta

## MODIFIED Requirements

### Requirement: The ask helper returns a complete state
The `ask` helper SHALL apply the guardrails, invoke a compiled graph with the initial state for a query that passes the input guards, and return the final `SupportState`. It SHALL accept an optional keyword-only `config` holding tags and metadata for the request's trace, and calling it without `config` SHALL behave as before. It SHALL NOT validate the query. Exceptions raised inside the graph SHALL propagate out of `ask`, and no partial state SHALL be returned.

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

#### Scenario: Trace configuration is optional
- **WHEN** `ask` is called with and without a `config` holding extra tags and metadata, on the same query and models
- **THEN** both calls return the same state, and the call with `config` records those tags and metadata on its trace's root run

#### Scenario: Blocked query
- **WHEN** `ask` runs a query the input guards block
- **THEN** the graph is not invoked, and the result has the safe fallback as `response`, `intent` `policy`, and empty `context` and `retrieved_sources`
