# Spec Delta

## ADDED Requirements

### Requirement: The classifier's model call belongs to the request
The injection classifier's model call SHALL be recorded as part of the request that made it: as a run beneath the request's root run in the same trace, uploaded with the same Social Security masking as every other run, and with its token usage collected for the request's timings and cost.

#### Scenario: Classifier run nests under the root
- **WHEN** a query passes the injection classifier with tracing enabled
- **THEN** the classifier's model run is a descendant of that query's root run, and no separate trace is created for it

#### Scenario: Classifier input is masked
- **WHEN** a query containing a full SSN pattern reaches the classifier with tracing enabled
- **THEN** the uploaded classifier run shows `[REDACTED:ssn]` in its place

#### Scenario: Classifier usage is collected
- **WHEN** the classifier model reports 150 input and 1 output tokens
- **THEN** the request's collected calls include that call with those tokens, with tracing on or off
