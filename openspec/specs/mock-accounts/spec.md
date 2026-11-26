# mock-accounts Specification

## Purpose

Defines the static mock account records that the account agent looks up, covering the account states and fields needed by later agent and guardrail work.

## Requirements

### Requirement: Account records are stored as static JSON
The system SHALL store mock accounts as a JSON array in `data/mock_accounts.json`, and account IDs MUST be unique and match the format `ACC-` followed by five digits.

#### Scenario: File parses and IDs are valid
- **WHEN** `data/mock_accounts.json` is parsed
- **THEN** it yields a list of records whose `account_id` values are unique and match `ACC-` plus five digits

### Requirement: Every record has the full field set
Every record SHALL contain `account_id`, `holder_name`, `account_type`, `balance` (number), `status`, `monthly_fee` (number), `monthly_fee_waived` (boolean), `overdraft_protection` (boolean), `recent_transactions` (list), and `ssn_last4` (string of four digits). Each transaction SHALL contain `date`, `description`, and `amount`.

#### Scenario: Required fields are present
- **WHEN** each record is checked against the field list
- **THEN** every field is present with the stated type, and every transaction has `date`, `description`, and numeric `amount`

### Requirement: Dataset covers each account state
The dataset SHALL contain exactly four accounts: two with status `active`, one `frozen`, and one `pending`. The frozen account SHALL also have a `freeze_reason`, and the pending account SHALL have no transactions.

#### Scenario: Status mix
- **WHEN** the records are grouped by `status`
- **THEN** there are two `active`, one `frozen`, and one `pending`

#### Scenario: Frozen account explains itself
- **WHEN** the frozen account is read
- **THEN** it has a non-empty `freeze_reason`

### Requirement: Lecture reference values are preserved
The record `ACC-12345` SHALL have holder `Alice Johnson`, type `Premium Checking`, balance `12450.75`, status `active`, monthly fee `12.99` with the waiver applied, and `ssn_last4` of `6789`. These values are used by the lecture's evaluation and guardrail examples.

#### Scenario: Reference account matches
- **WHEN** `ACC-12345` is looked up
- **THEN** every value above matches exactly

### Requirement: Account data is fictional and consistent with policy
All holder names and SSN fragments SHALL be fictional, and each account's type and monthly fee MUST match `account_fees.md`.

#### Scenario: Fees agree with the policy document
- **WHEN** an account's `account_type` is looked up in `account_fees.md`
- **THEN** the listed monthly fee equals the account's `monthly_fee`
