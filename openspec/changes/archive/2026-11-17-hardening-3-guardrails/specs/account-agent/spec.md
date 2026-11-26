# Spec Delta

## MODIFIED Requirements

### Requirement: The found answer is grounded in the full record
On `found`, the agent SHALL send a system message holding the account prompt with the record rendered as JSON without its `ssn_last4` field, and a human message holding the customer's question. The record and the question SHALL be supplied as values when the prompt is invoked, so braces in either are never read as template syntax.

#### Scenario: Prompt contents
- **WHEN** the agent answers "What is the balance on ACC-12345?"
- **THEN** the model receives one system message containing the record's JSON, including `12450.75`, and one human message equal to the question

#### Scenario: Braces are safe
- **WHEN** the record contains a description with `{` and `}`, and the question contains `{x}`
- **THEN** the agent calls the model without a template error, and both texts reach the model unchanged

#### Scenario: No Social Security data reaches the model
- **WHEN** the agent answers any question about `ACC-12345`
- **THEN** the system message contains neither the `ssn_last4` field nor `6789`
