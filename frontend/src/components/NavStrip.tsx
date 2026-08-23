/**
 * The bottom nav strip: four large counts on the ink ground.
 *
 * Big numerals, small labels, equal cells, hairline dividers. It is the only
 * place in the app where a number is allowed to be large — and even here it is a
 * count of orders, never a score.
 *
 * The fold from statuses to cells lives in `src/lib/nav.ts`.
 */

import type { ReactElement } from 'react'
import { navCells, type NavKey } from '../lib/nav'
import type { DashboardSummary } from '../types'

export interface NavStripProps {
  /** Null while the dashboard is still loading; cells then show an em dash. */
  summary: DashboardSummary | null
  /** Which cell reads as current. Null on the result screen. */
  active?: NavKey | null
  onSelect: (key: NavKey) => void
}

const HAIRLINE = 'rgba(255,255,255,.16)'

export function NavStrip({ summary, active, onSelect }: NavStripProps): ReactElement {
  const cells = navCells(summary)

  return (
    <nav
      // The gutter is on the strip, not on the cells: four equal cells still
      // divide the width evenly, and the first and last labels stay clear of the
      // outer 5% of the viewport where a projector's edge eats them.
      className="flex shrink-0 border-t-2 px-3 md:px-8 lg:px-12"
      style={{ background: 'var(--color-ink)', borderColor: HAIRLINE }}
      aria-label="ProofPay"
    >
      {cells.map((cell, i) => (
        <button
          key={cell.key}
          type="button"
          onClick={() => onSelect(cell.key)}
          aria-current={active === cell.key ? 'page' : undefined}
          className="flex-1 cursor-pointer px-2 py-3 text-left md:px-4 md:py-4"
          style={{
            // `min-w-0` generates nothing — the spacing scale has no 0 step — and
            // without it a cell refuses to shrink below its longest label.
            minWidth: 0,
            color: active === cell.key ? 'var(--color-on-field)' : 'var(--color-on-field-dim)',
            background: active === cell.key ? 'rgba(255,255,255,.08)' : 'transparent',
            borderRight: i < cells.length - 1 ? `2px solid ${HAIRLINE}` : undefined,
          }}
        >
          <b
            className="num block text-2xl font-extrabold"
            style={{ color: 'var(--color-on-field)', letterSpacing: '-0.02em' }}
          >
            {cell.value}
          </b>
          <span className="text-sm">{cell.label}</span>
        </button>
      ))}
    </nav>
  )
}
