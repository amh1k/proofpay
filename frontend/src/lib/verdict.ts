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
  // Screenshot reuse is answered BEFORE the contradiction sentence, and the
  // order is the fix rather than a preference. `R025` decides on the image
  // bytes alone: it never consults the ranking, so the rows it carries are a
  // comparison against whichever transaction happened to rank best for THIS
  // order — which can disagree with the receipt on every field, because it is
  // simply somebody else's payment. Measured live: a reused G01 checked against
  // order 1002 came back with amount, reference and sender all CONTRADICT, and
  // `onlyChangedSentence` printed "Only the amount, transaction ID and sender
  // name were changed." under the duplicate header. That is the SUSPICIOUS
  // family's forgery accusation, made against an honest customer, on the
  // strength of a comparison nothing in the verdict rested on.
  if (result.status === 'DUPLICATE' && result.reasons.includes('PROOF_REUSED')) {
    return 'Every detail matches because it is the same screenshot as before — the details were never re-typed.'
  }
  const only = onlyChangedSentence(result.evidence)
  if (only) return only
  if (result.status === 'DUPLICATE') {
    // A reused TRANSACTION: every field agrees, and that agreement IS the
    // finding — it is the same payment, not a second one.
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
 * The one observation that states an earlier order outright instead of leaving
 * it to be scraped. `core/proofs.py` emits `PROOF_PREVIOUSLY_SUBMITTED:<order>`
 * on every screenshot-reuse finding, in the `CODE:detail` shape the extractor's
 * notes already use.
 *
 * Reading it takes priority over `ORDER_REF` below, and not only for tidiness:
 * the regex demands a digit straight after `ORD`, so it finds `ORD-1041` but
 * misses an id like `order_demo_1001` — and misses it silently, leaving the
 * screen saying "search your orders" while the answer was sitting in the
 * payload. An id the engine handed us should never have to survive a regex.
 */
const PROOF_REUSE_NOTE = 'PROOF_PREVIOUSLY_SUBMITTED:'

/**
 * DUPLICATE: which earlier order already used this payment or this screenshot.
 *
 * There is still no dedicated field on the API, so this reads any order
 * reference the backend puts in `reasons`, `observations` or `summary`,
 * ignoring the order currently being checked. What that finds depends on which
 * duplicate it is, and the two are kept strictly apart. On screenshot reuse the
 * engine knows the answer and publishes it: `core/proofs.py` emits a
 * `PROOF_PREVIOUSLY_SUBMITTED:<order>` observation naming the order by the
 * merchant's own reference, and `explain()` names it in the summary, so this
 * returns something the merchant can actually look up. On an allocated
 * transaction the engine still only knows that the payment is spent, not what
 * spent it — so the note, which is about the IMAGE, is not read there, and this
 * returns null so the screen says how to find the order rather than naming the
 * wrong one.
 */
export function earlierOrderRef(result: VerificationResult): string | null {
  const current = result.order_id?.toUpperCase() ?? null

  // The note is read only on a verdict that is ABOUT the screenshot, and the
  // guard is load-bearing twice over.
  //
  // It names the order this IMAGE was accepted for, which is a different fact
  // from the one an `R020` verdict is making — there, the payment was spent by
  // whichever order holds the allocation, and that need not be the order the
  // picture was accepted for. Without this guard the row reads "Already used
  // for: A" under a claim about a transaction that order B actually spent, and
  // the merchant is sent to the wrong order.
  //
  // It is also what makes the DUPLICATE screen order-independent. `engine.py`
  // emits this note whenever proof history says so, not only when `R025` won,
  // so the demo's byte-identical G01/D01 pair gave order 1003 the note if and
  // only if 1001 had been checked (and approved) earlier in the same process —
  // the same order rendering two different sentences in one session.
  if (result.reasons.includes('PROOF_REUSED')) {
    for (const note of result.observations) {
      if (!note.startsWith(PROOF_REUSE_NOTE)) continue
      const ref = note.slice(PROOF_REUSE_NOTE.length).trim()
      if (ref && ref.toUpperCase() !== current) return ref
    }
  }

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
