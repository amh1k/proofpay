/**
 * The wire, folded into the shapes the screens already read.
 *
 * There are two dialects of the same API and the UI must never learn either:
 *
 *   MOCKS   `src/mocks/*.json`, generated from the real engine. Flat dashboard
 *           counts; a list whose items are whole verifications.
 *   LIVE    `backend/proofpay/api/v1`. `claim.proof_id` instead of `claim.id`;
 *           a dashboard of `{ total_checked, by_status }`; a list of thin
 *           summaries; evidence values that may arrive as NUMBERS (an amount is
 *           a paisa integer on that side of the wire, not a rendered string).
 *
 * Every response from either mode goes through here, including the mocks — a
 * mock that only works because it skips the adapter is a mock that lies. So the
 * screens see exactly one shape, and the day the backend renames a field this is
 * the one file that changes.
 *
 * Nothing here invents a value. A field that cannot be read becomes `null`, which
 * the evidence list renders as italic "not shown in this screenshot" (rule 8). A
 * status that cannot be read is an ERROR, not a guess — inventing a verdict is
 * the one failure this product cannot survive.
 */

import { formatMoney } from '../lib/money'
import type {
  Agreement,
  DashboardSummary,
  EvidenceItem,
  MatchedTransaction,
  PaymentClaimView,
  RiskLevel,
  VerificationResult,
  VerificationStatus,
  VerificationSummary,
} from '../types'

/* ── reading unknown JSON ──────────────────────────────────────────────────── */

type Json = unknown

function obj(value: Json): Record<string, Json> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, Json>)
    : null
}

function arr(value: Json): Json[] {
  return Array.isArray(value) ? value : []
}

/** A string, or null. An empty string is nothing, not a value. */
function str(value: Json): string | null {
  if (typeof value === 'string') return value.trim() === '' ? null : value
  return null
}

/** An integer count — paisa, or a tally. Never a rounded float. */
function int(value: Json): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.round(value)
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return Math.round(parsed)
  }
  return null
}

function float(value: Json, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function bool(value: Json, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function strList(value: Json): string[] {
  return arr(value)
    .map((v) => str(v))
    .filter((v): v is string => v !== null)
}

/* ── the closed vocabularies ───────────────────────────────────────────────── */

const STATUSES: ReadonlySet<string> = new Set([
  'VERIFIED',
  'UNMATCHED',
  'SUSPICIOUS',
  'DUPLICATE',
  'NEEDS_REVIEW',
])

const AGREEMENTS: ReadonlySet<string> = new Set(['AGREE', 'WEAK', 'CONTRADICT', 'MISSING'])

const RISKS: ReadonlySet<string> = new Set(['LOW', 'MEDIUM', 'HIGH'])

/** The one thing that must never be guessed. */
function status(value: Json): VerificationStatus {
  const raw = str(value)
  if (raw !== null && STATUSES.has(raw)) return raw as VerificationStatus
  throw new Error('The check came back in a shape ProofPay does not recognise.')
}

/**
 * An unreadable agreement becomes MISSING, which renders as a dashed ring and
 * the words "not shown on the receipt" — the only value that claims nothing
 * about the customer either way.
 */
function agreement(value: Json): Agreement {
  const raw = str(value)
  return raw !== null && AGREEMENTS.has(raw) ? (raw as Agreement) : 'MISSING'
}

/**
 * Read only so `risk` is not silently dropped from the type. Rule 1: it is never
 * rendered, here or anywhere else.
 */
function risk(value: Json): RiskLevel {
  const raw = str(value)
  return raw !== null && RISKS.has(raw) ? (raw as RiskLevel) : 'MEDIUM'
}

/* ── evidence ──────────────────────────────────────────────────────────────── */

/**
 * One side of an evidence row, as text.
 *
 * The live API sends an amount as a paisa integer (`500000`) where the mocks send
 * a rendered string (`"Rs 5000.00"`). Both have to end up as `"Rs 5,000"`, and
 * the number has to be formatted HERE — `displayValue` would read the bare digits
 * as rupees and multiply the figure by a hundred.
 */
export function evidenceValue(field: string, value: Json): string | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return field === 'amount' ? formatMoney(Math.round(value)) : String(value)
  }
  if (typeof value === 'boolean') return String(value)
  return str(value)
}

function adaptEvidence(value: Json): EvidenceItem {
  const raw = obj(value) ?? {}
  const field = str(raw.field) ?? 'detail'
  return {
    field,
    level_code: str(raw.level_code) ?? '',
    label: str(raw.label) ?? '',
    score: float(raw.score, 0),
    agreement: agreement(raw.agreement),
    claimed_value: evidenceValue(field, raw.claimed_value),
    recorded_value: evidenceValue(field, raw.recorded_value),
  }
}

/* ── the parts of a verification ───────────────────────────────────────────── */

function adaptClaim(value: Json): PaymentClaimView {
  const raw = obj(value) ?? {}
  return {
    // `proof_id` is the live name for the same thing.
    id: str(raw.id) ?? str(raw.proof_id) ?? '',
    provider: str(raw.provider),
    amount_minor: int(raw.amount_minor),
    currency: str(raw.currency) ?? 'PKR',
    sender_name: str(raw.sender_name),
    reference_id: str(raw.reference_id),
    occurred_at: str(raw.occurred_at),
  }
}

/**
 * The transaction that actually arrived — or null.
 *
 * Null when the engine matched nothing, and null when the payload cannot name an
 * amount, because a transaction without an amount would render an empty figure
 * beside a struck-through claim and read as "nothing arrived", which is a
 * different verdict.
 */
function adaptMatched(value: Json): MatchedTransaction | null {
  const raw = obj(value)
  if (raw === null) return null

  const amount = int(raw.amount_minor)
  const id = str(raw.id)
  if (amount === null || id === null) return null

  return {
    id,
    provider: str(raw.provider),
    amount_minor: amount,
    currency: str(raw.currency) ?? 'PKR',
    // The live projection omits the sender entirely; that is a real "not shown".
    sender_name: str(raw.sender_name),
    occurred_at: str(raw.occurred_at) ?? '',
  }
}

export function adaptVerification(value: Json): VerificationResult {
  const raw = obj(value)
  if (raw === null) throw new Error('The check came back empty.')

  const id = str(raw.id)
  if (id === null) throw new Error('The check came back without an id.')

  const matched = adaptMatched(raw.matched_transaction)

  return {
    id,
    order_id: str(raw.order_id),
    status: status(raw.status),
    stage: str(raw.stage) ?? '',
    risk: risk(raw.risk),
    confidence: float(raw.confidence, 0),
    claim: adaptClaim(raw.claim),
    matched_transaction: matched,
    // Never point at a transaction that did not survive `adaptMatched`.
    matched_txn_id: matched === null ? null : (str(raw.matched_txn_id) ?? matched.id),
    reasons: strList(raw.reasons),
    summary: str(raw.summary) ?? '',
    fired_rule_id: str(raw.fired_rule_id) ?? '',
    evidence: arr(raw.evidence).map(adaptEvidence),
    observations: strList(raw.observations),
    recommended_action: str(raw.recommended_action) ?? '',
    ruleset_version: str(raw.ruleset_version) ?? '',
    policy_fingerprint: str(raw.policy_fingerprint) ?? '',
    engine_version: str(raw.engine_version) ?? '',
    evaluated_at: str(raw.evaluated_at) ?? '',
    created_at: str(raw.created_at) ?? '',
    degraded: bool(raw.degraded, false),
  }
}

/* ── the list ──────────────────────────────────────────────────────────────── */

/**
 * The history, as the demo rail needs it: an id to replay and a status to name
 * the button. Both dialects reduce to this — the mocks carry whole verifications
 * in `items`, the live API carries thin summaries, and neither difference reaches
 * the screen.
 *
 * A row whose status cannot be read is DROPPED, not defaulted. A demo button
 * that promises the wrong verdict is worse than a missing button.
 */
export function adaptSummaries(value: Json): VerificationSummary[] {
  const raw = obj(value)
  const items = arr(raw?.items ?? value)

  const out: VerificationSummary[] = []
  for (const item of items) {
    const row = obj(item)
    if (row === null) continue
    const id = str(row.id)
    if (id === null) continue
    try {
      out.push({ id, order_id: str(row.order_id), status: status(row.status) })
    } catch {
      /* an unreadable status is a row we cannot label — skip it */
    }
  }
  return out
}

/* ── the dashboard ─────────────────────────────────────────────────────────── */

function count(value: Json): number {
  return int(value) ?? 0
}

/**
 * Four cells' worth of counts, from either dialect.
 *
 * Live sends `{ total_checked, by_status: { VERIFIED: 38, … } }`; the generated
 * mocks send the counts flat. `checked_today` falls back to the sum, so the strip
 * never shows a total smaller than the parts it is made of.
 */
export function adaptDashboard(value: Json): DashboardSummary {
  const raw = obj(value) ?? {}
  const by = obj(raw.by_status)

  const pick = (key: string, flat: string): number =>
    by !== null ? count(by[key]) : count(raw[flat])

  const verified = pick('VERIFIED', 'verified')
  const unmatched = pick('UNMATCHED', 'unmatched')
  const suspicious = pick('SUSPICIOUS', 'suspicious')
  const duplicate = pick('DUPLICATE', 'duplicate')
  const needsReview = pick('NEEDS_REVIEW', 'needs_review')

  const total = int(raw.total_checked) ?? int(raw.checked_today)
  const parts = verified + unmatched + suspicious + duplicate + needsReview

  return {
    checked_today: total ?? parts,
    verified,
    unmatched,
    suspicious,
    duplicate,
    needs_review: needsReview,
  }
}
