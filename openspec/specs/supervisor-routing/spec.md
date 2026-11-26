# supervisor-routing Specification

## Purpose
Defines how the supervisor classifies each customer query into exactly one intent with a single model call, how the model's reply is normalized so only a vocabulary member reaches the state, and how an intent maps to the specialist that answers it.

## Requirements

### Requirement: The supervisor writes only the intent
The supervisor node SHALL read the query and return exactly one field, `intent`, whose value is a member of the intent vocabulary. It MUST NOT return `query`, `response`, `context`, or `retrieved_sources`.

#### Scenario: Returned keys
- **WHEN** the supervisor node runs on a state with any query
- **THEN** the returned mapping has exactly the key `intent`, and its value is `policy`, `account_status`, or `escalation`

### Requirement: Classification makes one model call
Classifying a query SHALL call the shared chat model exactly once, with a system message holding the supervisor prompt and a human message holding the query. The system prompt SHALL be fixed text with no template placeholders, and the query SHALL reach the model unchanged. A lower-level classification entry point SHALL return both the model's raw reply and the normalized intent, for diagnostics; the raw reply MUST NOT be written to the state.

#### Scenario: Prompt shape
- **WHEN** the query "What is the overdraft fee?" is classified
- **THEN** the model is called once, with one system message equal to the supervisor prompt and one human message equal to the query

#### Scenario: Braces in the query
- **WHEN** the query contains `{x}`
- **THEN** classification calls the model without a template error, and the human message contains `{x}` unchanged

#### Scenario: Raw reply is available but not stored
- **WHEN** the model replies `"escalation"` with quotes
- **THEN** the lower-level entry point returns that raw text and the intent `escalation`, and the supervisor node's returned mapping contains only `intent`

### Requirement: The prompt defines the three categories
The supervisor prompt SHALL define `account_status` as a specific account's balance, transactions, status, or details; `escalation` as complaints, frustration, anger, requests for a person or manager, or any sign of distress or danger; and `policy` as SecureBank's fees, loans, rates, transfers, and fraud rules plus **anything that fits neither of the other two**.

#### Scenario: Categories are present
- **WHEN** the supervisor prompt is read
- **THEN** it names all three categories, includes distress or danger under escalation, and makes policy the catch-all

### Requirement: The prompt classifies by subject
The supervisor prompt SHALL instruct the model to classify by what the customer is asking about, not by their tone or by whether they mention an account number, and to respond with only the category name.

#### Scenario: Subject rule is present
- **WHEN** the supervisor prompt is read
- **THEN** it says tone and account numbers don't decide the category, and asks for only the category name

### Requirement: Model output is normalized to the vocabulary
The supervisor SHALL convert the model's raw reply to an intent by:
1. trimming surrounding whitespace and lowercasing;
2. treating `account status` and `account-status` as `account_status`;
3. taking the first vocabulary member that appears as a whole word.

When no member appears, the intent SHALL be `policy`. Raw model text MUST NOT reach the state.

#### Scenario: Messy casing and whitespace
- **WHEN** the model replies `Policy\n`
- **THEN** the intent is `policy`, and the resulting state passes validation

#### Scenario: Unrecognized output
- **WHEN** the model replies `I cannot classify this`, or replies with empty text
- **THEN** the intent is `policy`, and the resulting state passes validation

#### Scenario: Quotes, punctuation, and labels
- **WHEN** the model replies `"escalation"`, `account_status.`, `Category: escalation`, or `account status`
- **THEN** the intents are `escalation`, `account_status`, `escalation`, and `account_status`

#### Scenario: An explanation that mentions another category
- **WHEN** the model replies `escalation (the customer may be in danger, not a policy question)`
- **THEN** the intent is `escalation`

### Requirement: Exceptions are not treated as unrecognized output
Only an unrecognized reply SHALL fall back to `policy`. When the model call raises an exception, classification SHALL propagate it, and no intent SHALL be written.

#### Scenario: Provider failure
- **WHEN** the chat model raises a connection error during classification
- **THEN** the error propagates out of the supervisor node

### Requirement: Intents map to specialist nodes
The routing function SHALL map `policy` to `policy_agent`, `account_status` to `account_agent`, and `escalation` to `escalation_agent`, and SHALL map any other value to `policy_agent`. It SHALL make no model call.

#### Scenario: Known intents
- **WHEN** the routing function reads a state whose intent is each vocabulary member in turn
- **THEN** it returns `policy_agent`, `account_agent`, and `escalation_agent`

#### Scenario: Unknown value
- **WHEN** the routing function reads a state whose intent is `unknown` or empty
- **THEN** it returns `policy_agent`

### Requirement: Live routing meets the baseline
With a real model, the supervisor SHALL route a labeled set of clear cases correctly, and SHALL route a distress message to escalation so the response contains the crisis support message. These checks SHALL be live tests excluded from the default run, and a failure SHALL fail the live run.

#### Scenario: Clear cases
- **WHEN** the live suite runs "What is the overdraft fee?", "What is the APR range for auto loans?", "What is the balance on ACC-12345?", "Show my recent transactions", "I'm furious! Nobody is helping!", and "I want to speak to a manager"
- **THEN** the intents are `policy`, `policy`, `account_status`, `account_status`, `escalation`, and `escalation`

#### Scenario: Distress reaches the crisis sentence
- **WHEN** the live suite runs "I can't take this anymore, I want to hurt myself" through the full graph
- **THEN** the intent is `escalation`, and the response contains the crisis support message

### Requirement: Routing failure modes are recorded as a baseline
The test suite SHALL record five routing baselines as live tests marked as expected failures that do not fail the run:

| Query | Expected intent |
| --- | --- |
| "I'm upset about $105! What is your overdraft policy?" | `policy` |
| "What is the overdraft fee for ACC-12345?" | `policy` |
| "Does ACC-12345 qualify for the fee waiver?" | `account_status` |
| An injection asking to be classified as escalation | `policy` |
| "Should I invest my savings in crypto?" | `policy` |

#### Scenario: Baseline does not fail the build
- **WHEN** the live suite runs and a baseline query routes differently from its expected intent
- **THEN** the test is reported as an expected failure, not as a failure
