/**
 * Merchant-facing words. One place, so the register stays consistent.
 *
 * The register, in three rules:
 *
 *  1. Say what happened to the MONEY, not what the customer is. "Amount does not
 *     match", never "fraud detected". The transaction in a mismatch is real; only
 *     the amount was edited, and that distinction is the product.
 *  2. NOT FOUND speaks about what WE know — "no matching payment yet" — never
 *     about what the customer did.
 *  3. Every verdict ends with something the merchant can SAY BACK on WhatsApp.
 *     A verdict the merchant cannot act on is a verdict that wasted their time.
 */

import { amountGap, formatMoney } from './money'
import type { Agreement, VerificationResult, VerificationStatus } from '../types'

/** Rule 8. A field the OCR could not read renders as this, in italics. Never blank. */
export const NOT_SHOWN = 'not shown in this screenshot'

/** Rule 4 again, as a sentence — the reassurance line under a NOT FOUND verdict. */
export const NOT_AN_ACCUSATION =
  'This is not a sign that the receipt is fake. It only means the money has not arrived yet.'

/** Whose screenshot it is matters. The merchant must never have to guess. */
export const UPLOAD_TITLE = "Drop the customer's screenshot"
export const UPLOAD_HINT = 'or paste it, or pick one of the examples below'
export const UPLOAD_META =
  'Your provider SMS is already in ProofPay. The screenshot is only the claim.'

/* ── choosing the order ─────────────────────────────────────────────────────
 * A screenshot is never checked on its own — it is checked AGAINST an order, and
 * the merchant is the only one who knows which. These three lines are the whole
 * of that conversation. Rule 1 applies here too: they talk about the order and
 * the money, never about the customer.
 *
 * Rendered through the `cap` class, which uppercases; they are written lower-case
 * in source to match the other captions on that screen. */

/** The caption above the picker. It is a question because it is asking for one. */
export const ORDER_PICKER_HINT = 'which order is this payment for?'

/** Why "Check this payment" is not available yet. Says what to do, not what is wrong. */
export const ORDER_REQUIRED = 'choose the order above first'

/** Nothing to pick. Says what WE know, in the register of rule 2. */
export const ORDER_NONE = 'no orders are waiting for a payment right now'

export const CHECKING_TITLE = 'Checking against the payments that arrived'

/* ── the history list ───────────────────────────────────────────────────────
 * Headings say what the merchant is LOOKING AT, not what the app filtered by.
 * "Payments you approved" is a fact about their shop; "Filtered by VERIFIED" is
 * a fact about our query, and only one of those is worth the top of a screen. */
export const HISTORY_TITLE: Readonly<Record<'verified' | 'blocked' | 'review', string>> = {
  verified: 'Payments that checked out',
  blocked: 'Do not approve these',
  review: 'Worth a second look',
}

/**
 * Shown when a list has no rows. Rule 4 again — say what we know, not what
 * anyone did. "Nothing here yet" is a statement about the day, and a merchant
 * whose morning was quiet has not done anything wrong.
 */
export const HISTORY_EMPTY: Readonly<Record<'verified' | 'blocked' | 'review', string>> = {
  verified: 'No payments have checked out yet today.',
  blocked: 'Nothing has been flagged today. That is the normal case.',
  review: 'Nothing is waiting on you.',
}

/** The row's own label for a figure the screenshot never carried. Rule 8. */
export const HISTORY_NO_AMOUNT = 'amount not shown'

/** The bottom nav strip. Counts come from `DashboardSummary`. */
export const NAV_LABELS = {
  verified: 'Verified today',
  blocked: 'Do not approve',
  review: 'Need checking',
  check: 'Check a payment',
} as const

/** Accessible names for the per-field tick / cross / warning. Driven by `agreement`. */
export const AGREEMENT_LABEL: Readonly<Record<Agreement, string>> = {
  AGREE: 'matches',
  WEAK: 'weak match',
  CONTRADICT: 'does not match',
  MISSING: 'not shown on the receipt',
}

/** Engine field ids -> the words a shopkeeper uses. */
const FIELD_LABEL: Readonly<Record<string, string>> = {
  amount: 'Amount',
  reference: 'Transaction ID',
  sender_name: 'Sender name',
  timestamp: 'Time',
}

/** Human name for an evidence row. Unknown fields degrade to a tidy title case. */
export function fieldLabel(field: string): string {
  const known = FIELD_LABEL[field]
  if (known) return known
  const words = field.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

const PROVIDER_NAME: Readonly<Record<string, string>> = {
  jazzcash: 'JazzCash',
  easypaisa: 'Easypaisa',
  bank: 'your bank account',
}

/** "jazzcash" -> "JazzCash". Null -> "your account", which is always true. */
export function providerName(provider: string | null | undefined): string {
  if (!provider) return 'your account'
  const known = PROVIDER_NAME[provider.toLowerCase()]
  if (known) return known
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

/**
 * The two buttons under a verdict.
 *
 * Rule 5: `first` and `second` are READING ORDER, not importance. They must be
 * rendered at identical visual weight — same border, same padding, same type.
 * "Do not approve" styled louder than "Approve anyway" is the product deciding
 * for the merchant, which is exactly what it must not do.
 */
export interface VerdictActions {
  first: string
  second: string
}

export interface VerdictCopy {
  /** One sentence saying what we found. Rendered at `text-lede`, under the word. */
  lede: string
  /** What the merchant should do, in one short line. */
  advice: string
  /** What to say back to the customer on WhatsApp. Ready to copy. */
  reply: string
  /** Optional extra line. Present on UNMATCHED only. */
  note: string | null
  actions: VerdictActions
}

const ACTIONS: Readonly<Record<VerificationStatus, VerdictActions>> = {
  VERIFIED: { first: 'Use it', second: 'Not now' },
  SUSPICIOUS: { first: 'Do not approve', second: 'Approve anyway' },
  DUPLICATE: { first: 'Do not approve', second: 'Approve anyway' },
  NEEDS_REVIEW: { first: 'Check it myself', second: 'Approve anyway' },
  // Rule 4: nothing on a NOT FOUND screen approves anything. A payment that has
  // not arrived is not a judgement call to be nudged into; it is a wait.
  UNMATCHED: { first: 'Check again', second: 'Leave for later' },
}

const ADVICE: Readonly<Record<VerificationStatus, string>> = {
  VERIFIED: 'You can approve the order.',
  SUSPICIOUS: 'Do not approve the order yet.',
  DUPLICATE: 'Ask the customer for a new payment.',
  NEEDS_REVIEW: 'Check this payment yourself before approving.',
  UNMATCHED: 'Wait and check again before approving.',
}

/**
 * Everything the sign says, for one result.
 *
 * The verdict WORD is not here — it lives in `src/lib/status.ts` beside the colour
 * and the glyph, so the three can never drift apart. This is the prose.
 */
export function verdictCopy(result: VerificationResult): VerdictCopy {
  const claimed = result.claim.amount_minor
  const received = result.matched_transaction?.amount_minor ?? null
  const gap = amountGap(claimed, received)
  const where = providerName(result.matched_transaction?.provider ?? result.claim.provider)

  const actions = ACTIONS[result.status]
  const advice = ADVICE[result.status]

  switch (result.status) {
    case 'VERIFIED':
      return {
        lede:
          received === null
            ? result.summary
            : `${formatMoney(received)} reached ${where}. Every detail on the receipt matches.`,
        advice,
        reply:
          received === null
            ? 'Payment received — thank you. Your order is confirmed.'
            : `Received ${formatMoney(received)} — thank you. Your order is confirmed.`,
        note: null,
        actions,
      }

    case 'SUSPICIOUS':
      return {
        lede:
          gap && gap.direction !== 'EQUAL'
            ? `The screenshot claims ${formatMoney(claimed)}, but ${formatMoney(received)} was received.`
            : result.summary,
        advice,
        reply:
          gap && gap.direction === 'SHORT'
            ? `${formatMoney(received)} arrived, not ${formatMoney(claimed)}. Please send the remaining ${gap.amount}.`
            : 'The amount on this receipt does not match what reached my account. Please check and send again.',
        note: null,
        actions,
      }

    case 'DUPLICATE':
      // Two different accusations wear this one status word, and rule 1 makes
      // the distinction the product rather than a nicety. A reused TRANSACTION
      // means the money arrived once and is being spent twice. A reused
      // SCREENSHOT means the picture is a re-run — the payment behind it may be
      // perfectly good, and the merchant's next move is to ask for a fresh
      // receipt rather than to go hunting through an earlier order's money.
      // Saying "this payment was already used" on a reused screenshot states
      // something the engine did not find, and the customer can prove it wrong.
      if (result.reasons.includes('PROOF_REUSED')) {
        return {
          lede:
            'This is the same screenshot that was already used for an earlier order. The picture is a copy, not a second payment.',
          advice,
          reply:
            'This receipt was already sent to me for an earlier order. Please send a fresh payment for this one.',
          note: null,
          actions,
        }
      }
      return {
        lede:
          'This payment was already used for an earlier order. The money arrived once, not twice.',
        advice,
        reply:
          'This receipt was already used for an earlier order. Please send a fresh payment for this one.',
        note: null,
        actions,
      }

    case 'NEEDS_REVIEW':
      // The engine already words the ambiguity case for a human, and it alone
      // knows which rule fired. Prefer its sentence over a generic one of ours.
      return {
        lede: result.summary || 'We cannot tell which payment this receipt belongs to.',
        advice,
        reply:
          'Give me a few minutes to confirm this payment — I will message you as soon as it is done.',
        note: null,
        actions,
      }

    case 'UNMATCHED':
      return {
        lede: `Nothing matching this receipt has reached ${where} yet. Transfers can take a few minutes to arrive.`,
        advice,
        reply:
          'Your payment has not reached me yet. Transfers can take a few minutes — I will check again shortly.',
        note: NOT_AN_ACCUSATION,
        actions,
      }
  }
}
