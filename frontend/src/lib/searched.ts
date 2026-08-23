/**
 * "What we searched" — the honesty line under a NOT FOUND verdict.
 *
 * Rule 4 says NOT FOUND must not read as an accusation. Half of that is the
 * polarity flip — no fill, no colour, hollow glyph. The other half is this
 * sentence: the merchant is told what ProofPay actually looked through, so the
 * verdict reads as the limit of our knowledge rather than a judgement on their
 * customer.
 *
 * Which means it must never overstate. If we do not know how many payments were
 * scanned, the sentence says so by leaving the count out — it does not invent
 * "42". The count is a prop the API stage can start passing; until then the
 * wording stays true.
 *
 * Added for the verdict screens; not a foundation file.
 */

import { providerName } from './copy'
import { formatClock } from './time'
import type { VerificationResult } from '../types'

/**
 * How far either side of the receipt's own timestamp the engine looks for a
 * candidate. Kept here so the sentence and the search cannot drift apart once
 * the backend starts reporting its real window.
 */
export const SEARCH_WINDOW_MINUTES = 30

/** The accounts ProofPay reads the provider SMS from. */
const WATCHED_PROVIDERS: readonly string[] = ['easypaisa', 'jazzcash', 'bank']

export interface SearchWindow {
  /** Clock time, e.g. "08:35". */
  from: string
  to: string
}

/** The window either side of the claimed time. Null when the receipt showed no time. */
export function searchWindow(result: VerificationResult): SearchWindow | null {
  const iso = result.claim.occurred_at
  if (!iso) return null

  const at = new Date(iso).getTime()
  if (!Number.isFinite(at)) return null

  const span = SEARCH_WINDOW_MINUTES * 60 * 1000
  const from = formatClock(new Date(at - span).toISOString())
  const to = formatClock(new Date(at + span).toISOString())
  if (from === null || to === null) return null

  return { from, to }
}

/** "Easypaisa, JazzCash and your bank account". */
function providerPhrase(): string {
  const names = WATCHED_PROVIDERS.map(providerName)
  if (names.length === 0) return 'your account'
  if (names.length === 1) return names[0] ?? 'your account'
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1] ?? ''}`
}

/**
 * The sentence.
 *
 *     searchedSentence(result, 42)
 *     // "Searched 42 payments that arrived between 08:35 and 09:35 across
 *     //  Easypaisa, JazzCash and your bank account."
 *
 * Pass `null` for the count — the honest default — and it becomes "every payment
 * that arrived between …". Never pass a number the backend did not report.
 */
export function searchedSentence(result: VerificationResult, count: number | null): string {
  const scanned =
    count === null ? 'every payment that arrived' : `${String(count)} payments that arrived`
  const where = providerPhrase()
  const window = searchWindow(result)

  if (window === null) return `Searched ${scanned} today, across ${where}.`
  return `Searched ${scanned} between ${window.from} and ${window.to}, across ${where}.`
}
