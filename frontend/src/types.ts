/**
 * Types mirroring the ProofPay API.
 *
 * These are hand-kept in sync with `backend/proofpay/api/v1/schemas.py`, which is
 * itself built on the engine's `Decision`. See `docs/using-the-engine.md`.
 */

/** The five outcomes. UNMATCHED is *not* an accusation — the payment may still be settling. */
export type VerificationStatus =
  | 'VERIFIED'
  | 'UNMATCHED'
  | 'SUSPICIOUS'
  | 'DUPLICATE'
  | 'NEEDS_REVIEW'

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH'

/**
 * Which way a field's evidence points.
 *
 * Drive the tick/cross/warning icon from THIS, never from `score`. A field can
 * agree weakly — a very common name, say — without contradicting anything, and
 * rendering that as a red cross tells the merchant the opposite of the truth.
 */
export type Agreement = 'AGREE' | 'WEAK' | 'CONTRADICT' | 'MISSING'

/** One row of the result screen: what was claimed vs what the bank actually has. */
export interface EvidenceItem {
  field: string
  /** Stable machine id — safe to switch on. e.g. "NAME_INITIALS" */
  level_code: string
  /** Human wording, already written for you. e.g. "Match with initials expanded" */
  label: string
  score: number
  agreement: Agreement
  /** What the screenshot claimed. */
  claimed_value: string | null
  /** What the merchant's transaction record actually says. */
  recorded_value: string | null
}

export interface PaymentClaimView {
  id: string
  provider: string | null
  amount_minor: number | null
  currency: string
  sender_name: string | null
  reference_id: string | null
  occurred_at: string | null
}

export interface MatchedTransaction {
  id: string
  provider: string | null
  amount_minor: number
  currency: string
  sender_name: string | null
  occurred_at: string
}

export interface VerificationResult {
  id: string
  order_id: string | null
  status: VerificationStatus
  stage: string
  risk: RiskLevel
  /**
   * Confidence in THIS DECISION — derived from candidate margin and evidence
   * coverage. It is explicitly NOT a probability of fraud and must never be
   * rendered as a percentage.
   */
  confidence: number
  claim: PaymentClaimView
  matched_transaction: MatchedTransaction | null
  /** Deliberately null when two transactions matched equally well. */
  matched_txn_id: string | null
  reasons: string[]
  /** Merchant-facing headline, e.g. "The screenshot claims Rs 5,000, but Rs 500 was received." */
  summary: string
  fired_rule_id: string
  evidence: EvidenceItem[]
  observations: string[]
  /** e.g. "Do not approve the order yet." */
  recommended_action: string
  ruleset_version: string
  policy_fingerprint: string
  engine_version: string
  evaluated_at: string
  created_at: string
  degraded: boolean
}

/**
 * One row of the history, as the app actually uses it.
 *
 * `GET /verifications` returns whole verifications in the generated mocks and
 * thin list items from the live API. Everything the app does with that list —
 * build the demo rail, pick something to replay — needs an id and a status and
 * nothing else, so `src/api/adapt.ts` folds both dialects into this and no screen
 * ever has to know which backend it is talking to.
 */
export interface VerificationSummary {
  id: string
  order_id: string | null
  status: VerificationStatus
}

export interface DashboardSummary {
  checked_today: number
  verified: number
  unmatched: number
  suspicious: number
  duplicate: number
  needs_review: number
}

/**
 * Money crosses the wire as an integer count of paisa. Never a float.
 *
 * The implementation lives in `src/lib/money.ts` and is re-exported here so the
 * scaffold's original import path keeps working. There is exactly one formatter —
 * prefer importing it from `lib/money`, which also carries `amountGap`.
 */
export { formatMoney } from './lib/money'
