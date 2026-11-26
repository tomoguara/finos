# Spec Delta

## MODIFIED Requirements

### Requirement: Later-step modules exist with locked signatures
The package SHALL provide importable modules for the policy, account, escalation, and supervisor agents, the graph, and the `ask` invocation helper, each with its agreed signature and documentation. Once the core build is complete, no function in the package SHALL raise `NotImplementedError`.

#### Scenario: Stubs import without credentials
- **WHEN** every module is imported with no API key and no network access
- **THEN** all imports succeed

#### Scenario: Calling a stub
- **WHEN** the package's source is searched for `NotImplementedError` after Step 5 is applied
- **THEN** none is found, so no function remains a stub
