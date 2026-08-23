/**
 * The evidence rows, as data. Shared by every verdict family.
 *
 * Three jobs, all of which exist so no component has to think:
 *
 *  1. ORDER. What went wrong comes first — CONTRADICT, then WEAK, then MISSING —
 *     and everything that AGREED collapses into a single line at the end. That
 *     line is never deleted. On a mismatch the agreements are the proof that the
 *     transaction is REAL, which is the entire difference between this product
 *     and a fraud scanner.
 *  2. DISPLAY. The engine hands back `"Rs 5000.00"` and a raw ISO timestamp.
 *     Rule 7 wants `"Rs 5,000"`, so the value is reformatted here rather than in
 *     five different components with five different regexes.
 *  3. ROWS. `evidenceRows` is what was compared; `claimRows` is what the receipt
 *     alone says, for NOT FOUND, where there is no record to compare against.
 *
 * Ordering is driven by `agreement` and never by `score` — see the note on
 * `Agreement` in `src/types.ts`.
 *
 * Added for the verdict screens; not a foundation file.
 */

import { fieldLabel } from './copy'
import { formatMoney } from './money'
import { formatStamp } from './time'
import type { Agreement, EvidenceItem, VerificationResult } from '../types'

/** Worst first. AGREE is last because it may not appear as a row of its own. */
const FLAG_RANK: Readonly<Record<Agreement, number>> = {
  CONTRADICT: 0,
  WEAK: 1,
  MISSING: 2,
  AGREE: 3,
}

export interface EvidenceGroups {
  /** Rows that need reading, worst first. */
  flagged: EvidenceItem[]
  /** Rows that agreed. They collapse into one line — they are never dropped. */
  agreed: EvidenceItem[]
  /** How many fields were compared in total. */
  total: number
}

export function groupEvidence(items: readonly EvidenceItem[]): EvidenceGroups {
  const flagged = items
    .filter((i) => i.agreement !== 'AGREE')
    .sort((a, b) => FLAG_RANK[a.agreement] - FLAG_RANK[b.agreement])
  const agreed = items.filter((i) => i.agreement === 'AGREE')
  return { flagged, agreed, total: items.length }
}

/** Fields whose values are figures, ids or clock times — they get the `num` class. */
const NUMERIC_FIELDS: ReadonlySet<string> = new Set(['amount', 'reference', 'timestamp'])

export function isNumericField(field: string): boolean {
  return NUMERIC_FIELDS.has(field)
}

/**
 * `"Rs 5000.00"` -> `500000` paisa. Returns null on anything it does not fully
 * recognise, so an unexpected shape falls through to the raw string rather than
 * being silently rounded into a lie.
 */
function parseMoney(raw: string): number | null {
  const m = /^\s*(?:Rs\.?|PKR)?\s*([\d,]+)(?:\.(\d{1,2}))?\s*$/i.exec(raw)
  if (!m) return null
  const rupees = Number(m[1].replace(/,/g, ''))
  if (!Number.isFinite(rupees)) return null
  const paisa = m[2] ? Number(m[2].padEnd(2, '0')) : 0
  if (!Number.isFinite(paisa)) return null
  return rupees * 100 + paisa
}

/**
 * One evidence value, ready to render.
 *
 * Returns `null` when there is nothing to show — the caller renders `NOT_SHOWN`
 * in italics (rule 8). Never returns an empty string, never returns "missing".
 */
export function displayValue(field: string, raw: string | null): string | null {
  if (raw === null) return null
  const value = raw.trim()
  if (value === '') return null

  if (field === 'amount') {
    const minor = parseMoney(value)
    return minor === null ? value : formatMoney(minor)
  }
  if (field === 'timestamp') {
    return formatStamp(value) ?? value
  }
  return value
}

/* ── rows ──────────────────────────────────────────────────────────────────── */

/**
 * One rendered row. Values are display-ready; `null` means "there is nothing
 * here", and the list renders `NOT_SHOWN` in italics rather than a blank.
 *
 * `agreement` is null on rows that are not a comparison at all — the receipt's
 * own fields on a NOT FOUND verdict. A mark there would imply a judgement we did
 * not make.
 */
export interface EvidenceRow {
  key: string
  /** "Transaction ID". */
  label: string
  /** The engine's human wording, e.g. "Amount differs by a factor of ten". */
  detail: string | null
  claimed: string | null
  recorded: string | null
  agreement: Agreement | null
  numeric: boolean
}

/** What was compared, worst first, agreements last. */
export function evidenceRows(result: VerificationResult): EvidenceRow[] {
  const groups = groupEvidence(result.evidence)
  return [...groups.flagged, ...groups.agreed].map((item) => ({
    key: item.field,
    label: fieldLabel(item.field),
    detail: item.label,
    claimed: displayValue(item.field, item.claimed_value),
    recorded: displayValue(item.field, item.recorded_value),
    agreement: item.agreement,
    numeric: isNumericField(item.field),
  }))
}

/** How many of these rows agreed. Rows that are not a comparison do not count. */
function agreedRows(rows: readonly EvidenceRow[]): EvidenceRow[] {
  return rows.filter((r) => r.agreement === 'AGREE')
}

/**
 * The tail of the collapsed line: `"all 4 details match"`, `"3 details match"`,
 * `"1 detail matches"`. Null when nothing agreed — there is then no line to end.
 */
export function agreedSummary(rows: readonly EvidenceRow[]): string | null {
  const n = agreedRows(rows).length
  if (n === 0) return null
  const noun = n === 1 ? 'detail matches' : 'details match'
  return n === rows.length ? `all ${n} ${noun}` : `${n} ${noun}`
}

/** `"3 of 4 details match"` — the count beside the evidence heading. */
export function rowMatchCount(rows: readonly EvidenceRow[]): string | null {
  if (rows.length === 0) return null
  const noun = rows.length === 1 ? 'detail' : 'details'
  return `${agreedRows(rows).length} of ${rows.length} ${noun} match`
}

/**
 * What the receipt itself says, with nothing to compare it against.
 *
 * For NOT FOUND: no transaction arrived, so every row is one-sided by definition.
 * Reading the fields back to the merchant is what lets them go and look, and it
 * is deliberately not phrased as evidence for or against anybody.
 */
export function claimRows(result: VerificationResult): EvidenceRow[] {
  const claim = result.claim
  const rows: { key: string; value: string | null }[] = [
    { key: 'amount', value: claim.amount_minor === null ? null : formatMoney(claim.amount_minor, claim.currency) },
    { key: 'reference', value: claim.reference_id },
    { key: 'sender_name', value: claim.sender_name },
    { key: 'timestamp', value: formatStamp(claim.occurred_at) },
  ]

  return rows.map((row) => ({
    key: row.key,
    label: fieldLabel(row.key),
    detail: null,
    claimed: row.value,
    recorded: null,
    agreement: null,
    numeric: isNumericField(row.key),
  }))
}
