# Spec Delta

## Purpose

Defines the SecureBank policy documents the policy agent retrieves from, so that later retrieval and evaluation work can rely on known facts and one known conflict.

## ADDED Requirements

### Requirement: Corpus consists of four policy documents
The corpus SHALL contain exactly `account_fees.md`, `loan_policy.md`, `transfer_policy.md`, and `fraud_policy.md` in `data/policy-docs/`. Each document SHALL be between 450 and 550 words and written as original prose, not copied from the class repository.

#### Scenario: Corpus inventory and size
- **WHEN** the `data/policy-docs/` directory is listed and each file's words are counted
- **THEN** exactly the four named Markdown files exist, each with 450 to 550 words

### Requirement: Account fee facts
`account_fees.md` SHALL state: overdraft fee of $35 per transaction with a maximum of 3 per day ($105); overdraft protection transfer fee of $12; Premium Checking monthly fee of $12.99, waived with a balance above $1,500 or direct deposit of $500 or more; Basic Checking monthly fee of $0.

#### Scenario: Overdraft fact stays together
- **WHEN** `account_fees.md` is read
- **THEN** one sentence or table row states both the $35 fee and the $105 daily maximum

#### Scenario: Monthly fee waiver is stated
- **WHEN** `account_fees.md` is read
- **THEN** it contains $12.99, $1,500, and $500 in its Premium Checking waiver terms

### Requirement: Loan facts
`loan_policy.md` SHALL state: new auto APR 4.49%–12.99%; used auto APR 5.49%–14.99%; personal loan APR 6.99%–24.99%; minimum personal loan credit score of 620; late fee of $39 or 5% of the payment, whichever is less.

#### Scenario: Loan values are present
- **WHEN** `loan_policy.md` is read
- **THEN** it contains every APR bound, the 620 credit score, and the late fee terms above

### Requirement: Transfer facts
`transfer_policy.md` SHALL state: domestic wire $25 outgoing and free incoming; international wire $45 outgoing and $15 incoming; ACH limit of $10,000 per day, which can be raised to $25,000 on request.

#### Scenario: Transfer values are present
- **WHEN** `transfer_policy.md` is read
- **THEN** it contains each wire fee and both ACH limits above

### Requirement: Fraud facts are internally consistent
`fraud_policy.md` SHALL state zero liability for unauthorized transactions reported within 60 days, and MUST NOT contain a conflicting liability amount for reports made inside that window.

#### Scenario: Liability window is unambiguous
- **WHEN** `fraud_policy.md` is read
- **THEN** it states zero liability within 60 days and gives no $50 or $500 liability tier

### Requirement: Replacement-card conflict is preserved
The corpus SHALL keep one deliberate conflict: `account_fees.md` lists a replacement debit card at $5, and `fraud_policy.md` lists standard card replacement as free. Neither document MAY qualify its value, by mentioning fraud or otherwise, in a way that resolves the conflict.

#### Scenario: Both values are present and unqualified
- **WHEN** the replacement card entries in both documents are compared
- **THEN** `account_fees.md` says $5, `fraud_policy.md` says free, and neither limits its value to particular circumstances
