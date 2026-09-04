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
import type { VerificationSummary } from '../types'

export interface NavStripProps {
  /**
   * The checks this merchant has run — the same list a cell opens.
   *
   * The strip counts THIS rather than the dashboard endpoint, so a figure and
   * the list behind it can never disagree. See `src/lib/nav.ts`.
   *
   * Null while the request is in flight; cells then show an em dash, never a
   * zero.
   */
  items: VerificationSummary[] | null
  /** Which cell reads as current. Null on the result screen. */
  active?: NavKey | null
  onSelect: (key: NavKey) => void
}

const HAIRLINE = 'rgba(255,255,255,.16)'

export function NavStrip({ items, active, onSelect }: NavStripProps): ReactElement {
  const cells = navCells(items)

  return (
    <nav
      // The cells reach both viewport edges so an active first/last cell never
      // looks accidentally clipped. Extra padding on those two cells keeps the
      // labels clear of the outer 5% a projector may eat.
      className="flex shrink-0 border-t-2"
      style={{ background: 'var(--color-ink)', borderColor: HAIRLINE }}
      aria-label="ProofPay"
    >
      {cells.map((cell, i) => (
        <button
          key={cell.key}
          type="button"
          onClick={() => onSelect(cell.key)}
          aria-current={active === cell.key ? 'page' : undefined}
          className={
            'pp-interactive pp-nav-cell flex-1 cursor-pointer px-2 py-3 text-left' +
            ' first:pl-6 last:pr-6 md:px-4 md:py-4 md:first:pl-12 md:last:pr-12' +
            ' lg:first:pl-16 lg:last:pr-16'
          }
          style={{
            // `min-w-0` generates nothing — the spacing scale has no 0 step — and
            // without it a cell refuses to shrink below its longest label.
            minWidth: 0,
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
