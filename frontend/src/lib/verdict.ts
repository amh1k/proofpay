/**
 * Sentences the verdict screen derives from a result.
 *
 * Everything here is computed from data that is actually on the wire. Where the
 * API does not carry a fact — which earlier order spent a duplicated payment,
 * which two transactions were the ambiguous candidates — this file returns null
 * and the screen says so plainly. It never fills a gap with a plausible-looking
 * value: an invented order number on a rejection screen is worse than no number,
 * because the merchant will go and look for it.
 *
 * The register is the one set in `src/lib/copy.ts`: say what happened to the
 * money, never what the customer is.
 */

import { fieldLabel } from './copy'
import type { AmountGap } from './money'
import type { EvidenceItem, VerificationResult } from '../types'

/**
 * The line under the two amounts. `amountGap().text` is `"Rs 4,500 short"`; on
 * the sign it wants the noun it is short OF.
 */
export function deltaLine(gap: AmountGap | null): string | null {
  if (!gap || gap.direction === 'EQUAL') return null
  return gap.direction === 'SHORT'
    ? `${gap.amount} short of the order total`
    : `${gap.amount} more than the screenshot claims`
}

/** Shopkeeper words for a field, mid-sentence. `fieldLabel` is title case; this is not. */
const PLAIN_FIELD: Readonly<Record<string, string>> = {
  amount: 'amount',
  reference: 'transaction ID',
  sender_name: 'sender name',
  timestamp: 'time',
}

function plainField(field: string): string {
  return PLAIN_FIELD[field] ?? fieldLabel(field).toLowerCase()
}

/** `['a','b','c']` -> `"a, b and c"`. */
function joinList(parts: readonly string[]): string {
  if (parts.length === 0) return ''
  if (parts.length === 1) return parts[0]
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
}

/**
 * NEEDS_REVIEW: what every candidate has in common.
 *
 * A field that agreed (or agreed weakly) is a field that failed to separate the
 * candidates — which is precisely why the engine refused to pick one.
 */
export function sharedFieldsSentence(items: readonly EvidenceItem[]): string | null {
  const shared = items
    .filter((i) => i.agreement === 'AGREE' || i.agreement === 'WEAK')
    .map((i) => plainField(i.field))
  if (shared.length === 0) return null
  return `Both match on ${joinList(shared)}.`
}

/**
 * NEEDS_REVIEW: the field that would have decided it, and did not arrive.
 *
 * Ends in the `NOT_SHOWN` register — this is about what the screenshot did not
 * contain, not about what the customer withheld.
 */
export function separatorSentence(items: readonly EvidenceItem[]): string | null {
  const missing = items.filter((i) => i.agreement === 'MISSING').map((i) => plainField(i.field))
  if (missing.length === 0) return null
  const verb = missing.length === 1 ? 'it is' : 'they are'
  return `Only the ${joinList(missing)} would tell them apart, and ${verb} not shown in this screenshot.`
}

/**
 * SUSPICIOUS: the sentence that keeps a mismatch from reading as an accusation.
 *
 * "Only the amount was changed" is the whole product in five words — the
 * transaction is real, one field on the picture of it is not. Null unless
 * something actually contradicts, so it can never appear on a clean result.
 */
export function onlyChangedSentence(items: readonly EvidenceItem[]): string | null {
  const contradicting = items.filter((i) => i.agreement === 'CONTRADICT').map((i) => i.field)
  if (contradicting.length === 0) return null
  const names = contradicting.map(plainField)
  const verb = contradicting.length === 1 ? 'was' : 'were'
  return `Only the ${joinList(names)} ${verb} changed.`
}

/**
 * Why the collapsed line of ticks belongs on a screen that says no.
 *
 * Ticks under a rejection look like a contradiction until the sentence explaining
 * them is there, and on both rejections that sentence is the product:
 *
 *   SUSPICIOUS  only one field was changed, so the transaction is real
 *   DUPLICATE   every field agrees, and that is the point — it is the SAME
 *               payment, not a second one
 *
 * Null when there is nothing honest to add: NEEDS_REVIEW says it in the candidate
 * block instead, where the merchant is already looking.
 */
export function agreementMeaning(result: VerificationResult): string | null {
  const only = onlyChangedSentence(result.evidence)
  if (only) return only
  if (result.status === 'DUPLICATE') {
    return 'Every detail matches, because it is the same payment as before — not a second one.'
  }
  return null
}

/**
 * An order reference anywhere in a free-text field: `ORD-1041`, `ORDER 77`.
 *
 * Case-sensitive, and a digit is required immediately after the prefix. Both
 * matter: without them the sentence "already used for another order" matches
 * itself, and the screen tells the merchant to go and find order "order".
 */
const ORDER_REF = /\bORD(?:ER)?[-_ ]?\d[A-Z0-9-]*/g

/**
 * DUPLICATE: which earlier order already spent this transaction.
 *
 * The API has no field for it yet — the engine knows the transaction is
 * allocated, not what it is allocated to — so this reads any order reference the
 * backend happens to put in `reasons`, `observations` or `summary`, ignoring the
 * order currently being checked. Null means we genuinely do not know, and the
 * screen tells the merchant how to find it instead of naming one.
 */
export function earlierOrderRef(result: VerificationResult): string | null {
  const current = result.order_id?.toUpperCase() ?? null
  const haystacks = [...result.reasons, ...result.observations, result.summary]

  for (const text of haystacks) {
    const found = text.match(ORDER_REF)
    if (!found) continue
    for (const raw of found) {
      const ref = raw.trim()
      if (ref.toUpperCase() !== current) return ref
    }
  }
  return null
}

/** What to say when `earlierOrderRef` comes back null. Honest, and still actionable. */
export const EARLIER_ORDER_UNKNOWN = 'an earlier order — search your orders for this transaction'
