/**
 * Money.
 *
 * Rule 7: money crosses the wire as an INTEGER count of paisa and is formatted
 * with integer arithmetic only. `minor / 100` as a float is how you eventually
 * ship "Rs 4,499.999999" onto a projector.
 *
 * Grouping is done here rather than by `toLocaleString`, because the `en-PK`
 * grouping ICU picks is not the same in every browser and the figures on this
 * screen are the whole product.
 */

/** Rupee groups of three: 4500 -> "4,500". Integer input only. */
function group(whole: number): string {
  return String(whole).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/**
 * Format a paisa count for display: `500000` -> `"Rs 5,000"`.
 *
 * Paisa are shown only when they are non-zero, so the common case stays a clean
 * two-token figure. `null` renders as an em dash — for a field the OCR could not
 * read, use `NOT_SHOWN` from `src/lib/copy.ts` instead, never this.
 */
export function formatMoney(minor: number | null, currency = 'PKR'): string {
  if (minor === null || !Number.isFinite(minor)) return '—'

  const n = Math.trunc(minor)
  const sign = n < 0 ? '-' : ''
  const abs = Math.abs(n)
  const rupees = Math.floor(abs / 100)
  const paisa = abs - rupees * 100

  const body = paisa === 0 ? group(rupees) : `${group(rupees)}.${String(paisa).padStart(2, '0')}`
  const unit = currency === 'PKR' ? 'Rs' : currency

  return `${sign}${unit} ${body}`
}

/** Which way an amount is wrong. */
export type GapDirection = 'SHORT' | 'OVER' | 'EQUAL'

export interface AmountGap {
  /** Absolute difference, in paisa. `0` when the two agree. */
  minor: number
  /** SHORT: less arrived than the screenshot claims. OVER: more arrived. */
  direction: GapDirection
  /** Ready to render, e.g. `"Rs 4,500 short"`. Empty string when EQUAL. */
  text: string
  /** The figure alone, e.g. `"Rs 4,500"`. Empty string when EQUAL. */
  amount: string
}

/**
 * The difference between what the screenshot claimed and what actually arrived.
 *
 *     amountGap(500_000, 50_000).text  // "Rs 4,500 short"
 *
 * Returns `null` when either side is unknown — there is no honest sentence to
 * write about a difference you cannot compute.
 */
export function amountGap(
  claimedMinor: number | null,
  receivedMinor: number | null,
): AmountGap | null {
  if (claimedMinor === null || receivedMinor === null) return null
  if (!Number.isFinite(claimedMinor) || !Number.isFinite(receivedMinor)) return null

  const delta = Math.trunc(receivedMinor) - Math.trunc(claimedMinor)
  const minor = Math.abs(delta)

  if (delta === 0) return { minor: 0, direction: 'EQUAL', text: '', amount: '' }

  const amount = formatMoney(minor)
  const direction: GapDirection = delta < 0 ? 'SHORT' : 'OVER'
  const text = direction === 'SHORT' ? `${amount} short` : `${amount} more than claimed`

  return { minor, direction, text, amount }
}
