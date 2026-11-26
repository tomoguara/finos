# Spec Delta

## Purpose

Defines the `finos state` commands, which let a developer inspect the `SupportState` contract and validate and convert state values from a terminal or script, with no credentials or network.

## ADDED Requirements

### Requirement: State commands run offline without settings
Every `finos state` command SHALL work with no API key, no network access, and no `.env`. No `state` command SHALL load settings, so none changes the tracing environment.

#### Scenario: Settings stay unloaded
- **WHEN** every `state` command runs with the settings loader replaced by one that raises an error
- **THEN** all of them behave normally

### Requirement: Show displays the schema
`finos state show` SHALL list each `SupportState` field with its type and description, in contract order. With `--json` it SHALL print an object with `name` and a `fields` list whose entries have `name`, `type`, and `description`.

#### Scenario: Human output
- **WHEN** `finos state show` runs
- **THEN** it exits 0 and lists all five fields, with `retrieved_sources` shown as `list[str]`

#### Scenario: JSON output
- **WHEN** `finos state show --json` runs
- **THEN** stdout parses as JSON with `name` equal to `SupportState` and five entries in `fields`

### Requirement: Describe displays field ownership
`finos state describe` SHALL list each field's initial value, what writes it, and what reads it. It SHALL also show `history` as planned for Phase 2, separately from the five contract fields. With `--json` the planned field SHALL appear under a `planned` key.

#### Scenario: Human output
- **WHEN** `finos state describe` runs
- **THEN** it exits 0, shows `classify_intent` as the writer of `intent` and `policy_agent` as the writer of `context` and `retrieved_sources`, and has a line marking `history` as planned for Phase 2

#### Scenario: JSON output
- **WHEN** `finos state describe --json` runs
- **THEN** `fields` has exactly the five contract fields, and `planned` names `history`

### Requirement: Init prints a new state
`finos state init` SHALL print an initial state as indented JSON, with `query` taken from `--query` or empty if omitted, and all other fields at their initial values. It SHALL offer no options to pre-populate other fields.

#### Scenario: With a query
- **WHEN** `finos state init --query "What is the overdraft fee?"` runs
- **THEN** it exits 0, and stdout parses as JSON with that `query`, empty `intent`, `response`, and `context`, and an empty `retrieved_sources`

#### Scenario: Output passes validation
- **WHEN** the output of `finos state init` is passed to `finos state validate --file -`
- **THEN** `validate` exits 0

#### Scenario: Other fields cannot be set
- **WHEN** `finos state init --intent policy` runs
- **THEN** it exits 2

### Requirement: Input commands take exactly one source
`validate`, `serialize`, and `deserialize` SHALL read the state from exactly one of `--data/-d` (JSON text) or `--file/-f` (a path, where `-` means stdin). Providing both or neither SHALL exit 2 with a message on stderr. `--file` always names input; output goes to stdout or to `--output`.

#### Scenario: Inline data
- **WHEN** one of these commands runs with `--data` and a valid state
- **THEN** it exits 0

#### Scenario: File
- **WHEN** one of these commands runs with `--file` and a path to a valid state
- **THEN** it exits 0

#### Scenario: Stdin
- **WHEN** one of these commands runs with `--file -` and a valid state on stdin
- **THEN** it exits 0

#### Scenario: Both sources
- **WHEN** one of these commands runs with both `--data` and `--file`
- **THEN** it exits 2 and reports the problem on stderr

#### Scenario: Neither source
- **WHEN** one of these commands runs with neither `--data` nor `--file`
- **THEN** it exits 2 and reports the problem on stderr, without waiting on stdin

### Requirement: Unusable input is reported separately from invalid state
Input that cannot be read or parsed SHALL exit 2 with a message on stderr, and nothing on stdout, for all three input commands. This covers malformed JSON, a missing or unreadable file, and text that is not valid UTF-8.

#### Scenario: Malformed JSON
- **WHEN** one of these commands runs with `--data '{not json'`
- **THEN** it exits 2, reports the problem on stderr, and prints nothing to stdout

#### Scenario: Missing file
- **WHEN** one of these commands runs with `--file` and a path that does not exist
- **THEN** it exits 2, names the path on stderr, and prints nothing to stdout

### Requirement: Validation always checks the contract
All three input commands SHALL reject a value unless it is a JSON object, has all five fields and no others, has the contract's types, and has an `intent` that is empty or in the intent vocabulary. A state from mid-run with empty `response` or `context` SHALL be valid. All errors found SHALL be reported together, not just the first.

#### Scenario: Valid mid-run state
- **WHEN** a state with `intent` set to `policy` and empty `response` and `context` is validated
- **THEN** it is valid

#### Scenario: Not an object
- **WHEN** `[1, 2]` is validated
- **THEN** it is invalid, and the error says a JSON object is required

#### Scenario: Every problem is reported
- **WHEN** `{"query": "test", "intent": "unknown_intent"}` is validated
- **THEN** the errors name the bad `intent`, listing the valid values, and each of the missing `response`, `context`, and `retrieved_sources`

#### Scenario: Extra field
- **WHEN** an otherwise valid state that also has a `history` field is validated
- **THEN** it is invalid, and the error names `history`

#### Scenario: Wrong types
- **WHEN** a state with `retrieved_sources` set to the string `a.md`, or to a list containing a non-string, is validated
- **THEN** it is invalid, and the error names `retrieved_sources`

#### Scenario: Unnormalized intent
- **WHEN** a state with `intent` set to `Policy` is validated
- **THEN** it is invalid, and the error names `intent`

### Requirement: Validate reports a verdict on stdout
`finos state validate` SHALL write its verdict to stdout, exiting 0 for valid and 1 for invalid. With `--json` the verdict SHALL be an object with `valid` and an `errors` list.

#### Scenario: Valid state
- **WHEN** `finos state validate --data` runs with a valid state
- **THEN** it exits 0 and stdout reports a valid `SupportState`

#### Scenario: Invalid state
- **WHEN** `finos state validate --data` runs with `intent` set to `bad_value`
- **THEN** it exits 1 and stdout names `intent`

#### Scenario: JSON verdict
- **WHEN** `finos state validate --json` runs on an invalid state
- **THEN** it exits 1 and stdout parses as JSON with `valid` false and a non-empty `errors` list

### Requirement: Strict validation adds source and ownership checks
With `--strict`, `finos state validate` SHALL also require each `retrieved_sources` entry to exactly match a file name directly inside the policy documents directory, and SHALL reject non-empty `context` or `retrieved_sources` unless `intent` is `policy`. A missing policy documents directory SHALL exit 2.

#### Scenario: Known source
- **WHEN** a policy state with `retrieved_sources` of `["account_fees.md"]` is validated with `--strict`
- **THEN** it is valid

#### Scenario: Unknown source
- **WHEN** a policy state with `retrieved_sources` of `["nope.md"]` is validated with `--strict`
- **THEN** it is invalid, and the error names `nope.md`

#### Scenario: Path instead of a name
- **WHEN** a policy state with `retrieved_sources` of `["../config.toml"]` or `["data/policy-docs/account_fees.md"]` is validated with `--strict`
- **THEN** it is invalid, even though the path points to a real file

#### Scenario: Non-policy state with retrieval fields
- **WHEN** a state with `intent` of `account_status` or empty, and a non-empty `context`, is validated with `--strict`
- **THEN** it is invalid, and the error names `context`

#### Scenario: Policy state with no retrieval result
- **WHEN** a state with `intent` of `policy`, empty `context`, and empty `retrieved_sources` is validated with `--strict`
- **THEN** it is valid

#### Scenario: Checks are off by default
- **WHEN** a state with `retrieved_sources` of `["nope.md"]` is validated without `--strict`
- **THEN** it is valid

### Requirement: Serialize prints canonical JSON
`finos state serialize` SHALL validate its input and print it as indented JSON with fields in contract order. `--compact` SHALL print one line with no extra whitespace, and `--sort-keys` SHALL order fields alphabetically. Non-ASCII text SHALL be printed as is, not escaped. Because its output is already JSON, `--json` SHALL be accepted and change nothing.

#### Scenario: Contract order
- **WHEN** `finos state serialize` runs on a valid state whose fields are out of order
- **THEN** it exits 0, and stdout has the fields in the order `query`, `intent`, `response`, `context`, `retrieved_sources`

#### Scenario: Compact
- **WHEN** `finos state serialize --compact` runs on a valid state
- **THEN** stdout is a single line of JSON with no whitespace between tokens

#### Scenario: Sorted keys
- **WHEN** `finos state serialize --sort-keys` runs on a valid state
- **THEN** stdout has the fields in alphabetical order

#### Scenario: Same state, same output
- **WHEN** two valid states with equal values and different field order are serialized
- **THEN** the two outputs are byte-identical

#### Scenario: Non-ASCII text
- **WHEN** a valid state with `é` in `query` is serialized
- **THEN** stdout contains `é` and no `\u` escape for it

#### Scenario: JSON flag changes nothing
- **WHEN** `finos state serialize` runs on a valid state with and without `--json`
- **THEN** both print identical output

### Requirement: Deserialize prints a Python expression or validated JSON
`finos state deserialize` SHALL validate its input and print a `SupportState(...)` expression with fields in contract order. Evaluating that expression SHALL give a value equal to the input. With `--json` it SHALL print the validated state as indented JSON in contract order, the same as default `serialize`.

#### Scenario: Python expression
- **WHEN** `finos state deserialize --data` runs on a valid state with `query` of `test`
- **THEN** it exits 0, and stdout starts with `SupportState(query='test', ` and ends with the `retrieved_sources` value and a closing parenthesis

#### Scenario: Expression round trip
- **WHEN** the printed expression is evaluated with `SupportState` in scope
- **THEN** the result equals the input state

#### Scenario: JSON in either position
- **WHEN** `finos state deserialize --data` runs with `--json` after the command, and `finos --json state deserialize --data` runs on the same state
- **THEN** both exit 0 and print identical indented JSON

### Requirement: Converters refuse invalid state on stderr
`serialize` and `deserialize` SHALL exit 1 on an invalid state, reporting every error on stderr and printing nothing to stdout, including when `--json` is set.

#### Scenario: Redirected output stays clean
- **WHEN** `finos state serialize` runs on an invalid state with stdout redirected to a file
- **THEN** it exits 1, the errors appear on stderr, and the file is empty

#### Scenario: Deserialize with JSON requested
- **WHEN** `finos state deserialize --json` runs on an invalid state
- **THEN** it exits 1, the errors appear on stderr, and stdout is empty

### Requirement: Converters can write to a file
`serialize` and `deserialize` SHALL accept `--output/-o PATH` and write to PATH, as UTF-8, exactly the bytes they would otherwise print, honoring `--compact`, `--sort-keys`, and `--json`, with nothing on stdout. A PATH of `-` SHALL mean stdout. Missing parent directories SHALL be created. With `--verbose`, the path written SHALL be reported on stderr.

#### Scenario: Write to a file
- **WHEN** `finos state serialize --data` runs on a valid state with `--output` naming a new file
- **THEN** it exits 0, stdout is empty, and the file holds the same bytes the command prints without `--output`

#### Scenario: Formatting options apply to the file
- **WHEN** `finos state serialize --compact --sort-keys --output` runs on a valid state
- **THEN** the file holds one line of JSON with the fields in alphabetical order

#### Scenario: Deserialize to a file
- **WHEN** `finos state deserialize --output` runs on a valid state, with and without `--json`
- **THEN** the file holds the `SupportState(...)` expression, or the indented JSON with `--json`

#### Scenario: Dash means stdout
- **WHEN** `--output -` is given
- **THEN** the output is printed to stdout, as without `--output`

#### Scenario: Parent directories are created
- **WHEN** `--output` names a file inside directories that do not exist
- **THEN** the directories are created and the file is written

#### Scenario: Verbose names the destination
- **WHEN** a converter writes to `--output` with `--verbose`
- **THEN** stderr names the path, and stdout is still empty

### Requirement: Writing to a file never overwrites by accident
If the `--output` PATH exists, the converter SHALL exit 2 unless `--force` is given; `--force` without `--output` SHALL exit 2. A PATH that cannot be written SHALL exit 2 with a message on stderr. An invalid state SHALL exit 1 without creating or modifying PATH.

#### Scenario: Existing file is refused
- **WHEN** `--output` names a file that already exists and `--force` is not set
- **THEN** it exits 2, names the path on stderr, and the file is unchanged

#### Scenario: Force overwrites
- **WHEN** `--output` names an existing file and `--force` is set
- **THEN** it exits 0 and the file holds the new output

#### Scenario: Force without output
- **WHEN** `--force` is given without `--output`
- **THEN** it exits 2 and reports the problem on stderr

#### Scenario: Invalid state leaves the destination alone
- **WHEN** a converter runs on an invalid state with `--output`, with or without `--force`
- **THEN** it exits 1, the errors appear on stderr, a new path is not created, and an existing file is unchanged

#### Scenario: Unwritable destination
- **WHEN** `--output` names an existing directory
- **THEN** it exits 2 and reports the problem on stderr
