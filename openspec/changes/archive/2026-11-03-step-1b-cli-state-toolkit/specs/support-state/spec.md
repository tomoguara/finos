# Spec Delta

## ADDED Requirements

### Requirement: Field metadata is available at runtime
The state module SHALL expose, for each contract field, its description, initial value, writer, and readers. The metadata SHALL cover exactly the contract's fields and SHALL agree with the ownership documentation on the contract. Planned fields such as `history` SHALL be recorded separately and MUST NOT appear in the metadata or the contract.

#### Scenario: Metadata matches the contract
- **WHEN** the metadata's fields are compared with the declared fields of `SupportState`
- **THEN** they are the same five fields

#### Scenario: Metadata agrees with the documentation
- **WHEN** each field's writer and readers from the metadata are looked up in the `SupportState` documentation
- **THEN** each one appears there

#### Scenario: Planned field stays out of the contract
- **WHEN** the planned fields are read
- **THEN** they include `history`, and `history` is in neither the metadata nor the declared fields

### Requirement: Initial state can be built in one place
The state module SHALL provide a way to build an initial state from an optional query, with all other fields at their documented initial values. Each state built SHALL have its own `retrieved_sources` list.

#### Scenario: Initial values
- **WHEN** an initial state is built with `query` set to `test`
- **THEN** `query` is `test`, `intent`, `response`, and `context` are empty, and `retrieved_sources` is an empty list

#### Scenario: Lists are not shared
- **WHEN** two initial states are built and one's `retrieved_sources` is changed
- **THEN** the other's stays empty

### Requirement: Validation is opt-in and pure
The state module SHALL provide a validator that returns every problem found in a value, or nothing if it is valid. It SHALL NOT read files or settings; callers supply any known source names. The graph and agents MUST NOT depend on it, so ownership remains a documented convention at runtime.

#### Scenario: Valid value
- **WHEN** an initial state is validated
- **THEN** no problems are returned

#### Scenario: Several problems
- **WHEN** a value with a bad `intent` and a missing `response` is validated
- **THEN** both problems are returned

#### Scenario: Known sources come from the caller
- **WHEN** a policy state with `retrieved_sources` of `["a.md"]` is strictly validated, with `a.md` among the supplied names
- **THEN** no problems are returned, regardless of what is on disk

### Requirement: The policy agent records bare filenames
**Obligation on Step 2.** When the policy agent writes `retrieved_sources`, each entry SHALL be a bare filename such as `account_fees.md`, not a full or relative path as document loaders often report. Strict validation rejects anything else. Step 2 MUST add a test for this scenario, and this change records the obligation on the `policy_agent` stub.

#### Scenario: Policy agent output passes strict validation
- **WHEN** the implemented policy agent answers a query that retrieves documents, and its `retrieved_sources` are checked
- **THEN** every entry has no path separator and names a file in `data/policy-docs/`, so the resulting state passes strict validation

#### Scenario: Obligation is visible on the stub
- **WHEN** a developer reads the `policy_agent` documentation before Step 2
- **THEN** it states that `retrieved_sources` holds bare filenames

### Requirement: The supervisor writes a normalized intent
**Obligation on Step 5.** `classify_intent` SHALL write only a member of the intent vocabulary to `intent`: raw model output is normalized first, and unrecognized output becomes `policy`. Raw model text MUST NOT reach the state. Step 5 MUST add a test for this scenario, and this change records the obligation on the `classify_intent` stub.

#### Scenario: Messy model output
- **WHEN** the implemented supervisor receives model output with different casing or surrounding whitespace, such as `Policy\n`
- **THEN** the state's `intent` is `policy`, and the resulting state passes validation

#### Scenario: Unrecognized model output
- **WHEN** the implemented supervisor receives output outside the vocabulary
- **THEN** the state's `intent` is `policy`, and the resulting state passes validation

#### Scenario: Obligation is visible on the stub
- **WHEN** a developer reads the `classify_intent` documentation before Step 5
- **THEN** it states that only a normalized vocabulary member is written to `intent`
