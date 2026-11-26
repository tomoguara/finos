# Spec Delta

## MODIFIED Requirements

### Requirement: Later-step modules exist with locked signatures
The package SHALL provide importable modules for the policy, account, escalation, and supervisor agents, the graph, and the `ask` invocation helper. Each unimplemented function SHALL have its agreed signature and documentation, and calling it MUST raise an error naming the step that implements it.

#### Scenario: Stubs import without credentials
- **WHEN** every module is imported with no API key and no network access
- **THEN** all imports succeed

#### Scenario: Calling a stub
- **WHEN** an unimplemented function is called
- **THEN** it raises `NotImplementedError` naming its step
