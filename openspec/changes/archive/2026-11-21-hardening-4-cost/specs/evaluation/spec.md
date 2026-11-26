# Spec Delta

## ADDED Requirements

### Requirement: Results report cost per output
Every experiment SHALL report, over its scored outputs, the mean, p50, p95, and total of input tokens, output tokens, and cost, the guard share of cost, and the number of outputs whose cost is unknown. Each output's cost SHALL hold only the calls made for that output, even when outputs run concurrently.

#### Scenario: Cost beside latency
- **WHEN** the policy dataset is evaluated on OpenAI
- **THEN** the result reports mean, p50, and p95 cost per output, total cost, tokens, the guard share, and zero unknown outputs

#### Scenario: Concurrent outputs
- **WHEN** two outputs run at the same time and make different calls
- **THEN** each output's cost holds only its own calls

### Requirement: The judge's cost is reported separately
Every experiment that uses the judge SHALL report the judge's calls, tokens, and cost on their own, and SHALL NOT include them in any output's cost. A judge call with no reported usage SHALL make the judge's token count and cost unknown rather than undercount them.

#### Scenario: Judged dataset
- **WHEN** the escalation dataset is evaluated with the `gpt-4o-mini` judge
- **THEN** the result reports the judge's calls, tokens, and cost separately, and the per-output cost excludes them

#### Scenario: Judge without usage
- **WHEN** a judge call returns no token usage
- **THEN** the judge's tokens and cost are reported as unknown

### Requirement: The daily budget is checked after an experiment
At the end of an experiment, the daily budget SHALL be checked from the audit log, and a warning or alert SHALL be written to stderr when the 80% or 100% mark is reached. The experiment's results and exit code SHALL NOT change.

#### Scenario: Budget alert after a run
- **WHEN** an experiment ends and today's audited cost exceeds the daily budget
- **THEN** stderr carries one budget alert line and the run still exits 0
