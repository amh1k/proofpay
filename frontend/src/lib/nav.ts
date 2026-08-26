/**
 * The bottom nav strip, as data.
 *
 * Five engine statuses fold into four cells, because from the shopkeeper's side
 * of the counter an edited amount and an already-used payment are the same
 * decision: do not hand over the goods.
 */

import { NAV_LABELS } from './copy'
import type { VerificationStatus, VerificationSummary } from '../types'

export type NavKey = 'verified' | 'blocked' | 'review' | 'check'

/** The three cells that open a list. `check` opens the upload screen instead. */
export type FilterKey = Exclude<NavKey, 'check'>

/**
 * Which statuses each cell stands for.
 *
 * This is the SAME fold `navCells` counts with, written once so a cell can never
 * show a figure it does not then list. Read the two together: if `blocked` counts
 * `suspicious + duplicate`, tapping it must produce exactly those rows, or the
 * merchant is told there are three and shown two.
 */
export const NAV_STATUSES: Readonly<Record<FilterKey, readonly VerificationStatus[]>> = {
  verified: ['VERIFIED'],
  blocked: ['SUSPICIOUS', 'DUPLICATE'],
  review: ['NEEDS_REVIEW', 'UNMATCHED'],
}

/** Does this cell's list include that verdict? */
export function inFilter(key: FilterKey, status: VerificationStatus): boolean {
  return NAV_STATUSES[key].includes(status)
}

export interface NavCell {
  key: NavKey
  /** The large figure. `"+"` on the action cell, which counts nothing. */
  value: string
  label: string
}

/**
 * Four cells, in reading order.
 *
 * THE COUNTS COME FROM THE LIST THE CELL OPENS, not from `GET /dashboard/summary`.
 * That endpoint reports a whole day — 46 checks, 38 of them verified — while the
 * list holds the records the app can actually show. The two disagreed by design
 * and it did not matter while the cells were inert. It matters now: a cell that
 * can be TAPPED is a claim, and a merchant who reads 4 above "do not approve",
 * taps it and counts two rows has caught the product inventing a figure. On a
 * product whose whole argument is that it only tells you what it can show you,
 * that is the worst possible thing to be caught doing.
 *
 * So a count is `rows.filter(inFilter).length` and nothing else, and the two can
 * no longer drift. Making the strip read like a busy day is a job for more
 * history rows, not for a bigger number.
 *
 * A null list is "not loaded yet" and renders em dashes, never zeros — "0 need
 * checking" is a claim about the merchant's morning that we cannot make until
 * the request lands.
 */
export function navCells(items: VerificationSummary[] | null): NavCell[] {
  const tally = (key: FilterKey): string =>
    items === null ? '—' : String(items.filter((item) => inFilter(key, item.status)).length)

  return [
    { key: 'verified', value: tally('verified'), label: NAV_LABELS.verified },
    { key: 'blocked', value: tally('blocked'), label: NAV_LABELS.blocked },
    { key: 'review', value: tally('review'), label: NAV_LABELS.review },
    { key: 'check', value: '+', label: NAV_LABELS.check },
  ]
}
