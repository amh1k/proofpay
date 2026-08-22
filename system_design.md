# ProofPay — System Design

## 1. Document Purpose

This document defines the architecture of ProofPay for a hackathon-ready MVP.
ProofPay is an AI-assisted payment verification and reconciliation system for merchants who receive payment proofs through screenshots.
It converts a screenshot into a structured payment claim, compares that claim with merchant-side transaction records, detects reuse or suspicious inconsistencies, and returns an explainable decision.
The governing trust rule is:
> A screenshot is an untrusted claim. A merchant-side transaction record is the source of truth.
This document focuses on system boundaries, component responsibilities, data flow, decision logic, security, reliability, and architectural trade-offs.
It intentionally avoids detailed UI design, framework tutorials, and production-scale infrastructure that does not improve the hackathon demonstration.

## 2. Scope

### 2.1 MVP Goals
The MVP must:
- accept a payment screenshot;
- extract normalized payment fields;
- ingest or simulate trusted merchant transactions;
- identify the most likely matching transaction;
- detect amount and identity inconsistencies;
- detect reused transactions and screenshots;
- produce one explicit verification state;
- explain the evidence behind that state;
- retain verification history for audit and demonstration;
- isolate merchant data from other merchants.
### 2.2 MVP Non-Goals
The MVP will not:
- transfer, settle, refund, or custody money;
- connect directly to production bank accounts;
- guarantee detection of every manipulated image;
- use visual appearance alone to approve a payment;
- implement a full accounting or point-of-sale platform;
- introduce microservices, queues, or distributed inference without measured need;
- make irreversible business decisions on behalf of the merchant.
### 2.3 Quality Priorities
For the hackathon, priorities are ordered as follows:
1. Correct trust semantics.
2. Explainable and deterministic decisions.
3. A reliable end-to-end demonstration.
4. Clear module boundaries.
5. Security and tenant isolation.
6. Performance sufficient for interactive use.
7. A credible path to production scale.

## 3. Architectural Principles

### 3.1 Trusted Records Control Verification
OCR, image analysis, and similarity models produce evidence only.
`VERIFIED` requires a sufficiently matching trusted transaction that belongs to the same merchant.
### 3.2 Explainability Is a Domain Requirement
Every result must be traceable to typed evidence such as:
- transaction found;
- transaction ID matched;
- amount matched or conflicted;
- sender similarity score;
- timestamp distance;
- transaction already consumed;
- screenshot similarity detected;
- extraction confidence too low.
An opaque fraud probability is not an acceptable decision contract.
### 3.3 Deterministic Rules Wrap Probabilistic Models
OCR and computer vision may be probabilistic.
The final state transition is controlled by versioned business rules with explicit thresholds and precedence.
### 3.4 Build a Modular Monolith First
The MVP runs as one deployable backend with internal modules.
This preserves simple deployment and debugging while keeping boundaries that can later become independent workers or services.
### 3.5 Fail Safely
Missing evidence, model failures, and ambiguity must move a verification toward `NEEDS_REVIEW` or `UNMATCHED`, never toward a false approval.
### 3.6 Store Facts, Evidence, and Decisions Separately
ProofPay stores:
- the original input and its immutable metadata;
- extracted and normalized claims;
- trusted transaction facts;
- generated evidence;
- the final decision and rule version.
This separation supports audits, debugging, and future reprocessing.

## 4. System Context

```text
┌──────────────┐       payment proof        ┌──────────────┐
│   Customer   │ ─────────────────────────► │   Merchant   │
└──────────────┘                            └──────┬───────┘
                                                  │
                                                  │ verify
                                                  ▼
┌──────────────────┐  trusted transactions  ┌──────────────┐
│ Payment Provider │ ──────────────────────► │   ProofPay   │
│ or MVP Simulator │                         │              │
└──────────────────┘                         └──────┬───────┘
                                                  │
                                                  │ evidence-based result
                                                  ▼
                                           ┌──────────────┐
                                           │   Merchant   │
                                           └──────────────┘
```
### 4.1 Actors and Boundary
**Merchant user** uploads proofs, reviews outcomes, and manages transaction data.
**Customer** supplies the screenshot but does not directly control verification.
**Payment provider** is the eventual authoritative source of merchant transactions.
**Transaction simulator** replaces provider integrations in the hackathon MVP.
ProofPay owns claim extraction, normalization, matching, duplicate detection, decisioning, explanation, and audit history.
ProofPay does not own payment execution or provider settlement.

## 5. Container Architecture

```text
┌───────────────────────────────────────────────────────────┐
│                    Merchant Client                        │
│ Upload │ Result │ Review │ History │ Demo Transactions    │
└────────────────────────────┬──────────────────────────────┘
                             │ HTTPS
                             ▼
┌───────────────────────────────────────────────────────────┐
│                 ProofPay Application                      │
│                                                           │
│ API Boundary                                              │
│   │                                                       │
│   ├── Verification Orchestrator                           │
│   │     ├── Receipt Understanding                         │
│   │     ├── Transaction Matching                          │
│   │     ├── Duplicate Detection                           │
│   │     ├── Tamper Evidence                               │
│   │     └── Decision Engine                               │
│   │                                                       │
│   ├── Transaction Ingestion                               │
│   └── History and Review                                  │
└───────────────┬──────────────────────┬────────────────────┘
                │                      │
                ▼                      ▼
       ┌────────────────┐     ┌──────────────────┐
       │ Relational DB  │     │ Private Object   │
       │ Facts + audit  │     │ Storage: images  │
       └────────────────┘     └──────────────────┘
```
The browser client may use React and the backend may use FastAPI, but the architecture depends only on an HTTP client, an application runtime, a relational database, and private object storage.

## 6. Component Responsibilities

### 6.1 API Boundary
The API boundary handles authentication, authorization, request validation, upload limits, idempotency keys, transport mapping, and correlation identifiers.
It must not contain verification rules or provider-specific parsing logic.
### 6.2 Verification Orchestrator
The orchestrator creates the attempt, stores the proof, invokes analysis components, persists evidence, requests a decision, and returns the result.
It owns workflow order but does not implement OCR, matching, or decision rules itself.
### 6.3 Receipt Understanding
This component converts an image into a normalized `PaymentClaim`.
```text
Decode and normalize image
            ↓
Detect provider/template
            ↓
Run OCR with coordinates
            ↓
Extract semantic fields
            ↓
Normalize values
            ↓
Return claim + confidence
```
Provider adapters translate receipt-specific labels and layouts into one canonical contract.
Unknown templates fall back to a generic parser and normally produce lower confidence.
### 6.4 Transaction Ingestion
This component imports merchant-side transaction records through a stable provider-adapter interface.
For the MVP, a simulator or controlled CSV import implements that interface.
Future webhooks and provider polling can reuse the same normalized transaction model.
Ingestion deduplicates records by merchant, provider, and external transaction identity.
### 6.5 Transaction Matching
The matcher retrieves candidate transactions and scores each candidate against the claim.
It returns `MATCH`, `NO_MATCH`, or `AMBIGUOUS`; it does not return a final verification state.
### 6.6 Duplicate Detection
Duplicate detection covers two risks:
1. A trusted transaction was already consumed by another order or accepted verification.
2. The same or visually similar proof was submitted again.
Transaction reuse is deterministic and stronger than image similarity.
### 6.7 Tamper Evidence
Tamper analysis may detect inconsistent text, pasted regions, compression artifacts, or template anomalies.
It returns observations and confidence, never `VERIFIED` or `SUSPICIOUS` directly.
### 6.8 Decision Engine
The decision engine evaluates normalized evidence using a versioned rule set.
It produces status, risk, confidence, reason codes, and a merchant-facing explanation model.
### 6.9 Persistence Adapters
Repositories isolate domain logic from the database, while object-storage adapters isolate image handling from a specific cloud vendor.
These boundaries keep the design portable without creating unnecessary abstractions around internal pure functions.

## 7. Trust Model

| Source | Trust level | Architectural use |
|---|---|---|
| Provider transaction record | Trusted | Confirms money received |
| MVP transaction simulator | Trusted for demo | Replaces provider integration |
| Merchant CSV/manual import | Partially trusted | Candidate source with provenance |
| Customer screenshot | Untrusted | Payment claim only |
| OCR output | Derived, probabilistic | Matching input |
| Tamper score | Derived, probabilistic | Supporting warning |
| Similarity score | Derived, probabilistic | Reuse candidate |
| Decision rule output | Derived, reproducible | Final system response |
No screenshot-derived signal may independently establish that payment occurred.
All records carry provenance so the decision engine can distinguish provider evidence from demo or merchant-entered data.

## 8. Core Domain Model

### 8.1 Merchant
Owns users, transactions, proofs, orders, and verification attempts.
`merchant_id` is the tenant boundary and appears on every merchant-owned aggregate.
### 8.2 PaymentProof
Represents an immutable uploaded image with its merchant, private storage key, media metadata, cryptographic hash, perceptual hash, timestamps, and retention state.
### 8.3 PaymentClaim
Represents what the screenshot appears to claim.
```text
provider
amount_minor + currency
sender
receiver
external_transaction_id
occurred_at + timezone assumption
field_confidences
parser_version
```
Money is stored in integer minor units, never floating point.
Raw OCR output remains available for debugging but is not the canonical claim.
### 8.4 MerchantTransaction
Represents trusted or provenance-labelled payment evidence.
It includes provider identity, external ID, amount, parties, timestamp, ingestion source, and ingestion time.
### 8.5 VerificationAttempt
Represents one processing run for a proof and optional order.
It tracks lifecycle state, matched transaction, final status, rule version, timestamps, and failure information.
### 8.6 EvidenceItem
Represents one typed observation used by the decision engine.
```text
code
outcome: PASS | FAIL | WARNING | UNKNOWN
observed value
expected value
score
source component
component version
```
### 8.7 TransactionAllocation
Links a merchant transaction to the order or accepted verification that consumed it.
A uniqueness constraint prevents one transaction from being allocated twice unless a future business rule permits split payments.
### 8.8 AuditEvent
Records security-sensitive or decision-relevant actions without duplicating screenshots or secrets in logs.

## 9. Verification Lifecycle

```text
RECEIVED
   ↓
VALIDATING
   ↓
PROCESSING
   ↓
DECIDED ──────► REVIEWED
   │
   └──────────► FAILED
```
Attempt lifecycle is distinct from the payment decision.
A request can finish successfully with a payment status of `UNMATCHED` or `NEEDS_REVIEW`.
### 9.1 End-to-End Sequence
```text
Merchant     API       Orchestrator    Analyzers      Matcher       Decision
   │          │             │              │             │             │
   │ upload   │             │              │             │             │
   ├─────────►│ validate    │              │             │             │
   │          ├────────────►│ persist proof│             │             │
   │          │             ├─────────────►│ claim/signals             │
   │          │             │◄─────────────┤             │             │
   │          │             ├───────────────────────────►│             │
   │          │             │◄───────────────────────────┤             │
   │          │             ├────────────────────────────────────────►│
   │          │             │◄────────────────────────────────────────┤
   │          │◄────────────┤ persist decision                         │
   │◄─────────┤ result      │                                          │
```
### 9.2 Processing Order
1. Authenticate the merchant and validate the upload.
2. Create an idempotent verification attempt.
3. Store the original image in private object storage.
4. Compute exact and perceptual hashes.
5. Extract and normalize the payment claim.
6. Run screenshot reuse and tamper analysis.
7. Retrieve and score merchant transaction candidates.
8. Check transaction allocation and proof reuse.
9. Evaluate evidence using the active rule version.
10. Persist evidence and decision atomically.
11. Return an explanation-oriented response.
Independent image analyses may execute concurrently once the image is safely stored.
For the MVP they may execute in-process to avoid queue and worker complexity.

## 10. Transaction Matching Design

### 10.1 Normalization
Before comparison:
- case-fold and trim text;
- normalize Unicode and whitespace;
- canonicalize provider names;
- parse amounts into minor units;
- normalize transaction IDs by provider rules;
- preserve original and normalized values;
- convert timestamps to UTC while retaining source timezone assumptions.
### 10.2 Candidate Retrieval
Candidate retrieval narrows the merchant's transaction set using indexed filters: external transaction ID, provider, amount, bounded time window, and receiving account.
Retrieval should be generous enough to find edited claims while remaining bounded.
A transaction-ID match should still retrieve a candidate when the claimed amount was altered.
### 10.3 Candidate Scoring
Each candidate receives field-level scores.
```text
score = w_id       × id_similarity
      + w_amount   × amount_similarity
      + w_provider × provider_match
      + w_time     × time_proximity
      + w_sender   × sender_similarity
      + w_receiver × receiver_similarity
```
Transaction ID and amount receive the strongest weights.
Weights and thresholds belong to a rule version rather than scattered constants.
Critical conflicts remain explicit evidence even when the aggregate score is high.
### 10.4 Match Outcomes
`MATCH` means one candidate exceeds the acceptance threshold and is sufficiently separated from the runner-up.
`AMBIGUOUS` means multiple candidates are plausible or confidence separation is too small.
`NO_MATCH` means no candidate reaches the minimum threshold.
The matcher returns ranked candidates and field evidence so its result can be inspected.

## 11. Duplicate Detection Design

### 11.1 Transaction Reuse
An accepted payment allocates the matched transaction inside a database transaction.
The allocation table enforces uniqueness on the transaction identifier.
Concurrent attempts cannot both consume the same transaction: one succeeds and the other becomes `DUPLICATE` after conflict resolution.
### 11.2 Screenshot Reuse
The system compares SHA-256 for byte-identical files and perceptual hash distance for resized, compressed, or lightly cropped variants.
Perceptual matches are warnings until corroborated by transaction identity or review.
The MVP scans a merchant's recent proofs; cross-merchant comparison is prohibited because it would violate tenant boundaries and expose unrelated customer data.

## 12. Decision Model

### 12.1 Verification States
| State | Meaning | Merchant action |
|---|---|---|
| `VERIFIED` | Trusted transaction exists and critical fields agree | Continue order |
| `UNMATCHED` | No trusted transaction currently matches | Wait or inspect feed |
| `SUSPICIOUS` | A candidate exists but critical evidence conflicts | Do not approve automatically |
| `DUPLICATE` | Transaction or confirmed proof was already used | Reject reuse or review |
| `NEEDS_REVIEW` | Evidence is incomplete, ambiguous, or unavailable | Inspect manually |
### 12.2 Rule Precedence
Rules are evaluated in safety-first order:
1. Confirmed transaction reuse produces `DUPLICATE`.
2. Critical conflict on a strong candidate produces `SUSPICIOUS`.
3. Ambiguous candidates or low extraction confidence produce `NEEDS_REVIEW`.
4. No credible candidate produces `UNMATCHED`.
5. A unique trusted match with consistent critical fields produces `VERIFIED`.
Tamper evidence can strengthen `SUSPICIOUS` or trigger review, but cannot independently produce `VERIFIED`.
### 12.3 Example Decision Table
| Trusted match | Critical fields | Reuse | Confidence | Result |
|---|---|---|---|---|
| Yes | Consistent | No | Sufficient | `VERIFIED` |
| Yes | Conflicting | No | Sufficient | `SUSPICIOUS` |
| Yes | Any | Yes | Any | `DUPLICATE` |
| No | Unknown | No | Sufficient | `UNMATCHED` |
| Ambiguous | Unknown | No | Any | `NEEDS_REVIEW` |
| Any | Unknown | No | Insufficient | `NEEDS_REVIEW` |
### 12.4 Explanation Contract
The response includes final status, risk, summary, claimed fields, authorized matched fields, ordered reason codes, field outcomes, recommended action, rule version, and verification identifier.
The frontend formats this contract but must not reinterpret the decision.

## 13. API and Integration Boundaries

The transport may be REST, but domain contracts remain independent of HTTP.
Minimum capabilities are:
```text
Create verification
Read verification result
List verification history
Submit manual review outcome
Ingest/list merchant transactions
Read dashboard summary
```
Upload creation accepts an idempotency key so retries do not create multiple attempts.
Large images may later upload through short-lived signed URLs; a backend-mediated upload is simpler for the MVP.
Provider integrations implement:
```text
fetch or receive provider record
        ↓
validate source authenticity
        ↓
map to normalized transaction
        ↓
upsert idempotently
```
The simulator passes through the same normalization boundary as future integrations.

## 14. Data Consistency and Idempotency

The database is authoritative for verification state, transaction allocation, and audit records.
Key constraints include:
- every merchant-owned row includes `merchant_id`;
- provider transactions are unique within merchant and provider scope;
- accepted transaction allocations are unique;
- an idempotency key maps to one verification attempt per merchant;
- decisions reference immutable evidence and a rule version.
Proof storage and database writes cannot be one physical transaction.
The orchestrator therefore uses compensating behavior:
- if image upload fails, no processing begins;
- if database persistence fails after upload, mark or later remove the orphan object;
- if analysis fails, retain the attempt with failure metadata;
- never report success before the decision is persisted.

## 15. Security and Privacy

### 15.1 Authentication and Authorization
All merchant operations require authentication.
ProofPay uses role-based access control plus resource scopes. Every authorization check evaluates `merchant_id`, user role, requested action, and the user's assignment to the order, branch, or verification.

| Role | Permitted scope |
|---|---|
| `MERCHANT_ADMIN` | All merchant transactions, orders, proofs, users, and reports |
| `MANAGER` | Assigned branches, teams, orders, and related verification history |
| `VERIFIER` | Assigned orders only; can submit proofs and view their decisions |
| `REVIEWER` | Verification cases explicitly assigned for manual review |

A delivery rider is a `VERIFIER`, not a full merchant user. The rider may submit a proof for Order #145 and receive its verification result, but cannot browse the merchant's transaction feed or unrelated orders.

The matching engine may search the complete trusted transaction set internally. That internal search does not grant the requesting user access to the search results.

Verifier responses expose only the minimum necessary evidence: order, claimed amount, decision, reason codes, and optionally a masked transaction reference such as `TX••••91`.

No endpoint may return an unfiltered merchant transaction list to a verifier. Transaction ingestion, full transaction lookup, user management, and reporting remain administrator or manager capabilities.

Authorization is enforced server-side on every query, object lookup, download, and response projection using `merchant_id` and the user's scope. Hiding controls in the client is not a security boundary.
Object keys supplied by a client are never trusted as authorization proof.
### 15.2 Upload Security
The system enforces an image media-type allowlist, maximum compressed and decoded sizes, decode validation, randomized storage keys, and processing resource limits.
### 15.3 Storage Security
Screenshots live in encrypted private object storage.
Access uses short-lived signed URLs or authenticated backend streaming.
Database backups and object retention follow the same deletion policy.
### 15.4 Data Minimization
ProofPay does not request bank passwords, wallet credentials, or unrelated identity documents.
Logs exclude full OCR text, screenshots, access tokens, and unnecessary personal information.
### 15.5 Auditability
Audit events cover proof upload, transaction ingestion, decision creation, manual override, and access to sensitive evidence.
Manual overrides record actor, timestamp, previous state, new state, and reason.

## 16. Failure and Degradation Strategy

| Failure | System behavior | Result tendency |
|---|---|---|
| Image invalid | Reject before processing | No decision |
| OCR misses critical fields | Persist evidence gap | `NEEDS_REVIEW` |
| Provider feed delayed | Preserve attempt and allow retry | `UNMATCHED` |
| Multiple candidates | Return ranked ambiguity | `NEEDS_REVIEW` |
| Tamper analyzer unavailable | Mark evidence unavailable | Match-dependent |
| Duplicate analyzer unavailable | Do not silently approve | `NEEDS_REVIEW` |
| Object storage unavailable | Fail request safely | No decision |
| Database write fails | Do not report success | Retry/error |
| Processing timeout | Record incomplete attempt | `NEEDS_REVIEW` |
Component failures are isolated where safe, but trusted matching and duplicate checks are mandatory for automatic approval.
Retries are idempotent and bounded with backoff for external dependencies.

## 17. Observability

Every request carries `request_id`, `verification_id`, and `merchant_id` through structured logs and traces.
Core metrics are:
- end-to-end and per-stage latency;
- extraction success by provider/template;
- percentage by verification state;
- ambiguity and manual-review rates;
- transaction-feed freshness;
- duplicate-conflict count;
- component error and timeout rates.
Audit data and operational telemetry remain separate.
Alerts focus on broken flows, stale trusted data, elevated failure rates, and security events rather than normal `UNMATCHED` outcomes.

## 18. Testing Strategy

### 18.1 Contract and Rule Tests
Validate provider adapters, canonical schemas, evidence types, and response contracts.
Use table-driven tests for every state and precedence rule, proving absent or probabilistic evidence cannot accidentally produce `VERIFIED`.
### 18.2 Matching and Concurrency Tests
Cover exact IDs, altered amounts, sender variation, timestamp drift, ambiguity, and no-match cases.
Submit the same transaction concurrently and verify that at most one allocation succeeds.
Retry identical upload requests and verify idempotent attempt creation.
### 18.3 End-to-End Demo Set
The minimum dataset includes:
1. genuine payment;
2. edited amount with matching transaction ID;
3. nonexistent transaction;
4. reused transaction;
5. visually similar reused screenshot;
6. fuzzy sender-name match;
7. ambiguous transactions;
8. unreadable receipt;
9. unavailable optional analyzer;
10. cross-merchant access attempt.
The headline demo should show genuine, edited, reused, and ambiguous proofs.

## 19. MVP Deployment

```text
Internet
   │
   ▼
Static/Web Client
   │ HTTPS
   ▼
Application Container
   ├── API and domain modules
   ├── OCR and image processing
   └── verification orchestration
   │
   ├────────► Relational Database
   └────────► Private Object Storage
```
One backend application instance is sufficient for the hackathon if processing latency is bounded.
A React client and FastAPI application are practical implementation choices, with PostgreSQL for relational state and any S3-compatible private object store for images.
Configuration, secrets, thresholds, and rule versions are injected through the deployment environment.
The design avoids mandatory dependence on one cloud vendor.

## 20. Evolution Path

Scale only after measurements identify a bottleneck.
Likely evolution steps are:
1. Move long-running image analysis behind an internal job queue.
2. Add provider webhook consumers and reconciliation polling.
3. Autoscale OCR and vision inference workers.
4. Partition verification history when necessary.
5. Add a similarity index only when proof volume justifies it.
6. Separate services only where scaling or availability requirements differ.
An asynchronous production flow may become:
```text
API → durable job → analysis workers → decision engine → persisted result → notification
```
The domain contracts and evidence model remain stable across that transition.

## 21. Architectural Decisions

### ADR-001 — Merchant Transactions Are Authoritative
**Decision:** Require trusted merchant-side evidence for `VERIFIED`.
**Reason:** Screenshot appearance cannot prove that funds reached the merchant.
### ADR-002 — Use a Modular Monolith for the MVP
**Decision:** Keep API, orchestration, matching, and analysis in one deployable backend.
**Reason:** This minimizes operational risk while retaining clean boundaries.
### ADR-003 — Use an Evidence-Based Decision Engine
**Decision:** Produce states from typed evidence and versioned deterministic rules.
**Reason:** Financial decisions must be explainable, testable, and reproducible.
### ADR-004 — Separate Binary and Relational Storage
**Decision:** Store screenshots in private object storage and structured state in a relational database.
**Reason:** Each storage system is used for the workload it handles best.
### ADR-005 — Normalize Provider Data at the Boundary
**Decision:** Convert receipts and provider transactions into canonical domain models.
**Reason:** Decision logic should not know provider-specific layouts or payloads.
### ADR-006 — Simulate Trusted Transactions in the MVP
**Decision:** Use a simulator or import behind the production provider interface.
**Reason:** The demo validates reconciliation without unavailable banking integrations.
### ADR-007 — Keep Processing Synchronous Initially
**Decision:** Execute the bounded MVP pipeline within one request where latency permits.
**Reason:** It gives the simplest reliable demo and avoids premature queue infrastructure.
### ADR-008 — Make Transaction Consumption Atomic
**Decision:** Enforce allocation uniqueness in the database.
**Reason:** Application-level duplicate checks are unsafe under concurrency.
### ADR-009 — Version Models and Rules
**Decision:** Persist parser, model, threshold, and rule versions with evidence.
**Reason:** Results must remain explainable when implementations change.

## 22. Architecture Fitness Criteria

The MVP architecture is successful when:
- no screenshot can be `VERIFIED` without a trusted transaction match;
- the same transaction cannot be accepted twice under concurrency;
- every result contains inspectable reason codes;
- provider formats do not leak into decision rules;
- analyzer failure degrades safely;
- a verifier cannot browse unrelated transactions from the same merchant;
- merchant data is isolated across all storage boundaries;
- genuine, edited, reused, unmatched, and ambiguous cases are repeatable;
- the complete system can be deployed and debugged by a small team.

## 23. Summary

ProofPay is a reconciliation system, not merely an image classifier.
```text
Acquire evidence
      ↓
Understand the screenshot claim
      ↓
Reconcile against trusted transactions
      ↓
Apply explicit rules and explain the result
```
The screenshot tells ProofPay what the customer claims happened.
The merchant transaction feed tells ProofPay what actually happened.
The verification engine compares those accounts, prevents reuse, and produces a safe, auditable merchant decision.
