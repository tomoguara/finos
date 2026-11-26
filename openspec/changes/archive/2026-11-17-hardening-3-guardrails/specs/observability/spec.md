# Spec Delta

## MODIFIED Requirements

### Requirement: Root runs carry a fixed tag vocabulary
Every root run SHALL carry an `entry:<point>` tag naming the entry point and a `provider:<name>` tag naming the configured provider. A graph root SHALL also carry `intent:<intent>`, added once the query has been routed. A root where a guardrail did anything but pass SHALL carry `guardrail:<decision>`. The `exp:` and `eval-` prefixes are reserved and SHALL NOT be set by this capability.

#### Scenario: Intent tag after routing
- **WHEN** a query routed to the account agent is traced from the command line
- **THEN** its root run carries the tags `entry:supervisor-ask`, `provider:<configured provider>`, and `intent:account_status`
