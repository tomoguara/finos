# Spec Delta

## MODIFIED Requirements

### Requirement: Ask prints the escalation reply
`finos escalation ask --query <text>` SHALL run the escalation agent standalone through the guardrails and exit 0 on success, including when a guard blocks or replaces the reply. In human mode it SHALL print the response, which already ends with the support contact block, with no trailer line. With `--json` it SHALL print the complete `SupportState`.

#### Scenario: Human output
- **WHEN** `finos escalation ask --query "I'm furious! Nobody is helping!"` runs and the agent answers
- **THEN** it exits 0 and stdout ends with the support contact block

#### Scenario: JSON output
- **WHEN** the same command runs with `--json`
- **THEN** stdout is a JSON object with the five contract fields, `intent` equal to `escalation`, and empty `context` and `retrieved_sources`, and it passes `finos state validate --strict`

#### Scenario: Verbose shows the raw reply
- **WHEN** the command runs with `--verbose`
- **THEN** the provider and model, the model's raw reply before the guards and the contact block, and whether the fallback message was used are written to stderr, and stdout and the exit code are the same as without `--verbose`
