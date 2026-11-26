# Spec Delta

## ADDED Requirements

### Requirement: Account IDs are extracted and normalized
The system SHALL find account IDs in free text as `ACC` (any casing), then an optional single space or dash, then exactly five digits not followed by another digit, and SHALL normalize each to `ACC-` plus the five digits. It SHALL return the distinct normalized IDs in order of first appearance.

#### Scenario: Accepted forms
- **WHEN** IDs are extracted from queries containing `ACC-12345`, `acc-12345`, `ACC 12345`, or `ACC12345`
- **THEN** each yields exactly `["ACC-12345"]`

#### Scenario: Rejected forms
- **WHEN** IDs are extracted from queries containing only `ACC-1234`, `ACC-123456`, `XY-12345`, `ACCT-12345`, or a bare `12345`
- **THEN** each yields no IDs

#### Scenario: Duplicates collapse
- **WHEN** IDs are extracted from "Is ACC-12345 the same as acc 12345? What about ACC-67890?"
- **THEN** the result is `["ACC-12345", "ACC-67890"]`

### Requirement: A bare token can be normalized
The system SHALL normalize a token that consists only of an accepted account ID form, and SHALL reject any token with other content.

#### Scenario: Bare token
- **WHEN** the token ` acc-12345 ` is normalized
- **THEN** the result is `ACC-12345`

#### Scenario: Token with extra content
- **WHEN** the token `ACC-12345x` or `ACC-1234` is normalized
- **THEN** no ID is returned

### Requirement: Account records load from the mock file
The system SHALL read `data/mock_accounts.json` on each load and index the records by `account_id`. A missing file SHALL raise `FileNotFoundError` naming the path. Content that is not valid JSON, or not a list of objects each holding `account_id`, SHALL raise `ValueError` naming the path. The module SHALL import only the standard library and `finos.config`.

#### Scenario: Shipped records
- **WHEN** the shipped records are loaded
- **THEN** `ACC-12345`, `ACC-67890`, `ACC-11111`, and `ACC-22222` are present, and `ACC-99999` is not

#### Scenario: Missing file
- **WHEN** the records file does not exist
- **THEN** loading raises `FileNotFoundError` naming its path

#### Scenario: Corrupt file
- **WHEN** the records file holds invalid JSON
- **THEN** loading raises `ValueError` naming its path

#### Scenario: Empty list
- **WHEN** the records file holds an empty JSON array
- **THEN** loading succeeds and every lookup finds nothing

### Requirement: A query resolves to exactly one outcome
The system SHALL resolve a query to one outcome: `no_id` when no ID is extracted, `multiple_ids` when more than one distinct ID is extracted (without looking any up), and otherwise `found` with the record or `not_found`. The resolution SHALL carry the extracted IDs.

#### Scenario: Found
- **WHEN** "What is the balance on ACC-12345?" is resolved
- **THEN** the outcome is `found`, the IDs are `("ACC-12345",)`, and the record's holder is `Alice Johnson`

#### Scenario: Not found
- **WHEN** "What is the balance on ACC-99999?" is resolved
- **THEN** the outcome is `not_found` and there is no record

#### Scenario: No ID
- **WHEN** "Show my recent transactions" is resolved
- **THEN** the outcome is `no_id` and there are no IDs

#### Scenario: Multiple IDs
- **WHEN** "Compare ACC-12345 and ACC-67890" is resolved
- **THEN** the outcome is `multiple_ids`, the IDs are `("ACC-12345", "ACC-67890")`, and there is no record
