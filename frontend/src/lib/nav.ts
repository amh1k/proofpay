/**
 * The bottom nav strip, as data.
 *
 * Five engine statuses fold into four cells, because from the shopkeeper's side
 * of the counter an edited amount and an already-used payment are the same
 * decision: do not hand over the goods.
 */

import { NAV_LABELS } from './copy'
import type { DashboardSummary } from '../types'

export type NavKey = 'verified' | 'blocked' | 'review' | 'check'

export interface NavCell {
  key: NavKey
  /** The large figure. `"+"` on the action cell, which counts nothing. */
  value: string
  label: string
}

/** Four cells, in reading order. A null summary renders em dashes, never zeros. */
export function navCells(summary: DashboardSummary | null): NavCell[] {
  return [
    {
      key: 'verified',
      value: summary ? String(summary.verified) : '—',
      label: NAV_LABELS.verified,
    },
    {
      key: 'blocked',
      value: summary ? String(summary.suspicious + summary.duplicate) : '—',
      label: NAV_LABELS.blocked,
    },
    {
      key: 'review',
      value: summary ? String(summary.needs_review + summary.unmatched) : '—',
      label: NAV_LABELS.review,
    },
    { key: 'check', value: '+', label: NAV_LABELS.check },
  ]
}
