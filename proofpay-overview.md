# ProofPay – AI-Powered Payment Verification & Reconciliation

## 1. Overview

**ProofPay** is an AI-assisted payment verification and reconciliation system designed for small merchants, online sellers, delivery businesses, and shops receiving digital payments through services such as Easypaisa, JazzCash, Raast, and bank transfers.

Instead of trusting a customer's payment screenshot or forcing the merchant to manually search through different payment apps, ProofPay extracts the payment details from the screenshot and matches them against the merchant's trusted transaction records.

The original concept describes ProofPay as a **payment-proof firewall** that detects edited and reused screenshots by matching them against merchant-side transaction evidence.

The key idea is:

> **The screenshot is only a payment claim. The merchant's transaction record is the source of truth.**

---

## 2. Problem

When customers pay digitally, merchants often receive screenshots as proof of payment.

Several problems can occur:

- The amount in a screenshot may have been edited.
- A completely fake transaction screenshot may be presented.
- A genuine screenshot may be reused for another order.
- An old transaction may be presented as a new payment.
- The merchant may receive payments across several banks and wallets.
- Employees or delivery riders may not have access to the business owner's bank accounts.
- Online sellers may have to manually reconcile dozens or hundreds of screenshots with incoming transactions.

A merchant can manually open Easypaisa or their banking app and verify a transaction, but this becomes inconvenient when dealing with **multiple payment providers, employees, deliveries, orders, or large numbers of transactions**.

ProofPay automates this reconciliation process.

---

## 3. Core Features

### Payment Screenshot Understanding

The merchant uploads or scans the customer's payment screenshot.

ProofPay uses OCR and layout understanding to extract:

- payment provider
- amount
- sender
- receiver
- transaction/reference ID
- date and time

For example:

```json
{
  "provider": "Easypaisa",
  "amount": 5000,
  "sender": "Muhammad Ali",
  "transactionId": "TX928391",
  "timestamp": "2026-08-22 16:32"
}
```

OCR, layout understanding and payment-field extraction are part of the original ProofPay AI workflow.

### Unified Merchant Transaction Feed

ProofPay maintains a normalized transaction feed containing payments received by the merchant.

In a production version, transactions could come from:

- Easypaisa
- JazzCash
- Raast
- banks
- payment APIs/webhooks
- payment notifications or exports

For the hackathon, this can be a **simulated transaction feed**, which is also the approach recommended in the original proposal.

Example:

```text
TX1001 | Easypaisa | Rs 2,000 | Ali   | 10:22
TX1002 | JazzCash  | Rs   500 | Ahmed | 10:31
TX1003 | Bank      | Rs 3,000 | Sara  | 10:43
```

### Intelligent Transaction Matching

ProofPay searches the merchant's transaction feed for the payment represented in the screenshot.

It compares:

- transaction ID
- amount
- sender
- timestamp
- provider

Matching does not always need to be exact.

For example:

```text
Screenshot: Muhammad Ali
Transaction: M. Ali
```

or:

```text
Screenshot: 4:31 PM
Transaction: 4:32 PM
```

ProofPay can use fuzzy matching and confidence scores to determine whether the records likely represent the same payment.

### Edited Screenshot Detection

ProofPay analyzes the screenshot for possible manipulation.

Examples include:

- changing Rs. 500 to Rs. 5,000
- modifying the transaction ID
- changing the transaction date
- changing the recipient name

Image-forensics signals provide additional evidence, but ProofPay should **never verify or reject a payment based only on whether the screenshot visually looks genuine**. The trusted transaction record remains the stronger evidence.

### Duplicate and Reused Payment Detection

A genuine transaction can still be used fraudulently.

For example:

```text
TX5001
Rs 3,000
```

is used to approve:

```text
Order #102
```

Later, the same transaction screenshot is submitted for:

```text
Order #145
```

The bank transaction is genuine, but the payment has already been associated with another order.

ProofPay detects this and returns:

```text
DUPLICATE PAYMENT PROOF

Transaction TX5001 was already used
for Order #102.
```

ProofPay can check both:

- previously used transaction IDs
- visually similar previously submitted screenshots

Duplicate detection is part of the original ProofPay concept.

### Explainable Verification

ProofPay should not simply return:

```text
Fraud probability: 87%
```

Instead, it should explain the evidence.

Example:

```text
PAYMENT NOT VERIFIED

Screenshot amount: Rs 5,000
Actual received:   Rs   500

✓ Transaction ID exists
✗ Amount does not match
✓ Timestamp matches
⚠ Possible editing detected around amount field

Risk: HIGH

Recommended action:
Do not approve the order yet.
```

This makes the system understandable and useful to the merchant.

### Merchant Dashboard and History

Merchants can see recent payment checks and their results.

```text
Payments checked today: 46

Verified:       38
Unmatched:       3
Suspicious:      2
Duplicates:      2
Needs review:    1
```

Each verification can also be linked to an order, customer, delivery, or sale.

---

## 4. End-to-End Flow

```text
Customer sends/shows payment screenshot
                    │
                    ▼
           Screenshot uploaded
                    │
                    ▼
       OCR + Layout Understanding
                    │
                    ▼
       Structured Payment Claim
                    │
          ┌─────────┴─────────┐
          │                   │
          ▼                   ▼
 Screenshot Forensics    Duplicate Search
          │                   │
          └─────────┬─────────┘
                    │
                    ▼
          Transaction Matching
                    ▲
                    │
      Merchant Transaction Feed
 Easypaisa / JazzCash / Bank / Raast
                    │
                    ▼
          Evidence Fusion Engine
                    │
                    ▼
             Final Decision
                    │
      ┌─────────────┼──────────────┐
      ▼             ▼              ▼
  VERIFIED      SUSPICIOUS      DUPLICATE
                    │
             or UNMATCHED /
             NEEDS REVIEW
```

The most important part of this flow is that **AI interprets the untrusted screenshot, while merchant-side transaction evidence performs the actual verification**.

---

## 5. Verification Results

ProofPay can return five main results.

### VERIFIED

```text
✅ PAYMENT VERIFIED

Rs 2,000 received.
Transaction TX1001 matches the submitted proof.
```

### UNMATCHED

```text
❓ PAYMENT NOT FOUND

No matching merchant transaction was found.
```

This should not automatically mean fraud because a payment may still be processing.

### SUSPICIOUS

```text
⚠ PAYMENT DETAILS DO NOT MATCH

Screenshot: Rs 5,000
Received:   Rs   500
```

### DUPLICATE

```text
🔁 PAYMENT ALREADY USED

This transaction was previously linked
to another order.
```

### NEEDS REVIEW

```text
⚠ MANUAL REVIEW REQUIRED

Two possible transactions match this screenshot.
```

The original MVP proposes verified, unmatched, suspicious-edit and duplicate outcomes; **Needs Review** is a useful additional state for uncertain cases.

---

## 6. Example Scenario

Consider an Instagram seller receiving an order worth **Rs. 5,000**.

The customer sends a screenshot claiming:

```text
Transaction ID: TX9001
Amount: Rs 5,000
Time: 3:42 PM
```

ProofPay extracts these details and finds:

```text
Merchant transaction:

TX9001
Rs 500
3:42 PM
```

The system also identifies suspicious changes around the amount region.

ProofPay returns:

```text
⚠ SUSPICIOUS PAYMENT

Transaction ID: MATCH
Timestamp:      MATCH
Screenshot:     Rs 5,000
Actual payment: Rs   500

Possible amount manipulation detected.

Do not approve the order.
```

The merchant does not need to manually open the banking application and search through their transactions.

---

## 7. Hackathon MVP

The hackathon version should remain focused.

### Must-Have Features

- Merchant login
- Screenshot upload or camera capture
- OCR and payment-field extraction
- Support for 1–2 payment receipt formats
- Simulated merchant transaction feed
- Transaction matching
- Fuzzy sender/time matching
- Amount mismatch detection
- Duplicate transaction detection
- Basic screenshot manipulation analysis
- Explainable verification result
- Verification history/dashboard
- Five verification states:
  - Verified
  - Unmatched
  - Suspicious
  - Duplicate
  - Needs Review

The original proposal recommends roughly **30 realistic receipts with genuine, edited, and reused variants** for the prototype.

### Strong Bonus Features

If time remains:

- Easypaisa/JazzCash automatic provider detection
- Screenshot similarity search
- suspicious-region visualization
- Urdu/Roman Urdu interface
- Urdu voice confirmation
- linking payments directly to orders
- merchant analytics

---

## 8. Live Demo

A simple four-case demo can explain the entire project.

### Case 1: Genuine Payment

```text
Screenshot: Rs 2,000
Actual:     Rs 2,000

✅ VERIFIED
```

### Case 2: Edited Screenshot

```text
Screenshot: Rs 5,000
Actual:     Rs   500

⚠ SUSPICIOUS
Amount mismatch detected.
```

### Case 3: Reused Payment

```text
Transaction TX1003 exists,
but was already used for Order #41.

🔁 DUPLICATE
```

### Case 4: Ambiguous Payment

```text
Two transactions could match.

⚠ NEEDS REVIEW
```

The first three cases closely follow the original proposal's recommended live demo: a valid screenshot, an edited amount, and a reused screenshot.

---

## 9. Final Product Positioning

ProofPay should **not** be pitched simply as:

> "AI that detects fake payment screenshots."

That makes the project unnecessarily easy to challenge.

The stronger positioning is:

> **ProofPay is an AI-powered payment verification and reconciliation layer that converts customer payment proofs into structured claims, matches them against trusted merchant transactions across payment providers, and prevents unmatched, altered, or reused payments from approving orders.**

The bank or wallet remains the source of truth.

**ProofPay's value is automating the work between the customer's payment proof, the merchant's transaction records, and the order that is supposed to be paid.**
