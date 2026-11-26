# policy-agent Specification

## Purpose

Defines the grounded-answer policy node: the prompt that keeps answers to the retrieved context, how the agent writes `response`, `context`, and `retrieved_sources` into `SupportState`, and the standalone `ask_policy` helper that runs it without the graph.

## Requirements

### Requirement: The policy agent writes only the fields it owns
`policy_agent` SHALL read `query` and return exactly `response`, `context`, and `retrieved_sources`. It MUST NOT return `query` or `intent`. `context` SHALL be the formatted context the model was given, and `retrieved_sources` SHALL list the distinct source filenames of the retrieved chunks in rank order, so the most relevant source comes first.

#### Scenario: Returned keys
- **WHEN** `policy_agent` runs on a state with a query
- **THEN** the returned mapping has exactly the keys `response`, `context`, and `retrieved_sources`

#### Scenario: Sources are distinct and ranked
- **WHEN** the top three chunks come from `account_fees.md`, `account_fees.md`, and `fraud_policy.md`, in that order
- **THEN** `retrieved_sources` is `["account_fees.md", "fraud_policy.md"]`

#### Scenario: Context is what the model saw
- **WHEN** `policy_agent` runs
- **THEN** the returned `context` is exactly the context string placed in the model's prompt

### Requirement: Answers are generated from the retrieved context
The agent SHALL call the shared chat model once, with a system message holding the policy grounding prompt with the formatted context filled in, and a human message holding the customer's question.

#### Scenario: Prompt contents
- **WHEN** the agent answers "What is the overdraft fee?"
- **THEN** the model receives one system message containing the formatted context and one human message equal to the question

#### Scenario: Nothing retrieved still generates
- **WHEN** retrieval returns no chunks
- **THEN** the model is still called with an empty context, `context` is empty, `retrieved_sources` is empty, and the agent does not raise

#### Scenario: Agent response is the model's text
- **WHEN** the model replies with a message
- **THEN** `response` is that message's text

### Requirement: The prompt enforces grounding
The grounding prompt SHALL instruct the model to use only the context, to reply with the fixed not-found message when the answer is not there, to quote amounts, percentages, and conditions exactly, not to speculate or give financial advice, and to present both values and note the discrepancy when the context conflicts. The not-found message SHALL be defined once and SHALL NOT include contact details that are absent from the corpus.

#### Scenario: Prompt carries the rules
- **WHEN** the grounding prompt is read
- **THEN** it contains the not-found message, a placeholder for the context, and no placeholder for the question

#### Scenario: No invented contact details
- **WHEN** the not-found message is read
- **THEN** it contains no email address or phone number

### Requirement: The policy agent can run without the graph
`ask_policy(query)` SHALL build an initial state for the query, set `intent` to `policy`, run `policy_agent`, and return the complete state with the agent's fields merged in. The result SHALL pass strict state validation with the corpus filenames as known sources.

#### Scenario: Complete state
- **WHEN** `ask_policy("What is the overdraft fee?")` is called
- **THEN** the result has all five contract fields, `query` is the question, and `intent` is `policy`

#### Scenario: Result passes strict validation
- **WHEN** the result of `ask_policy` is validated strictly with the filenames in `data/policy-docs/` as known sources
- **THEN** no problems are returned

### Requirement: Importing the agent has no side effects
Importing `finos.agents` or `finos.agents.policy` MUST NOT load settings, open or build the index, or contact a model or embedding provider. The index SHALL be opened on the agent's first call.

#### Scenario: Import without credentials
- **WHEN** the agents package is imported with no API key, no Ollama host, and no `data/chroma/` directory
- **THEN** the import succeeds and `data/chroma/` is not created

### Requirement: The default answers meet the baseline facts
With real models, the policy agent SHALL answer the explore doc's acceptance questions from the corpus. These checks SHALL be live tests, run on request and excluded from the default test run.

#### Scenario: Overdraft fee
- **WHEN** the live suite asks "What is the overdraft fee?"
- **THEN** the response contains `$35` and `retrieved_sources` includes `account_fees.md`

#### Scenario: Auto loan APR
- **WHEN** the live suite asks "What is the APR range for auto loans?"
- **THEN** the response contains `4.49%` or `12.99%` and `retrieved_sources` includes `loan_policy.md`

#### Scenario: Out-of-scope question
- **WHEN** the live suite asks "What is the stock market outlook?"
- **THEN** the response contains the not-found message's opening, "I don't have that information"

### Requirement: Known failure modes are recorded as a baseline
The test suite SHALL record the lecture's failure modes for the baseline configuration (a fact split across chunks, a relevant but wrong document ranked first for the replacement-card question, a hallucinated amount, and empty retrieval), so the evaluation phase has something to measure. Live failure-mode tests SHALL be marked as expected failures that do not fail the run. The split-fact case SHALL also have an offline check of which chunks hold the overdraft and overdraft protection facts.

#### Scenario: Baseline does not fail the build
- **WHEN** the live suite runs and a failure mode reproduces
- **THEN** the test is reported as an expected failure, not as a failure

#### Scenario: Chunk placement is recorded offline
- **WHEN** the default suite chunks the corpus at 1000/100
- **THEN** a test records whether `$35` and `$105`, and the overdraft protection `$12` fee and its description, land in the same chunk
