# Spec Delta

## Purpose

Defines the single shared state that flows through the support graph, so that every agent, the caller, and the evaluation layers agree on its shape and meaning.

## ADDED Requirements

### Requirement: State has exactly five fields
The `SupportState` contract SHALL declare exactly these fields: `query` (string), `intent` (string), `response` (string), `context` (string), and `retrieved_sources` (list of strings). The core build MUST NOT add other fields, including the Phase 2 `history` field.

#### Scenario: Field set is checked
- **WHEN** the declared fields of `SupportState` are inspected
- **THEN** they are exactly `query`, `intent`, `response`, `context`, and `retrieved_sources`, with the types above

#### Scenario: Contract can be imported and instantiated
- **WHEN** a caller imports `SupportState` from `finos.state` and builds a value with `query` set to `"test"`, empty strings for the other string fields, and an empty list for `retrieved_sources`
- **THEN** the import succeeds without any API key or network access, and the value's `query` reads back as `"test"`

### Requirement: Intent vocabulary is defined with the contract
The state module SHALL expose the three valid intent values, `policy`, `account_status`, and `escalation`, both as a type and as a runtime collection. The `intent` field SHALL remain a plain string so that it can hold the empty initial value.

#### Scenario: Vocabulary is available at runtime
- **WHEN** a consumer reads the valid intents collection
- **THEN** it contains exactly `policy`, `account_status`, and `escalation`

#### Scenario: Initial intent is valid for the contract
- **WHEN** a state is created with `intent` set to the empty string
- **THEN** it conforms to the contract, and the empty string is not in the valid intents collection

### Requirement: Field ownership is documented on the contract
The contract's documentation SHALL state each field's initial value and which component writes it: `intent` by the supervisor, `response` by the specialist agent, and `context` and `retrieved_sources` by the policy agent only. Ownership is a documented convention and MUST NOT require a runtime validation layer in the core build.

#### Scenario: Ownership can be read from the contract
- **WHEN** a developer reads the documentation of `SupportState`
- **THEN** it gives the initial value and writer for all five fields, and states that `context` and `retrieved_sources` belong to the policy agent only
