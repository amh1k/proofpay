/**
 * The small mark at the head of an evidence row.
 *
 * Four agreements, four different silhouettes — the same discipline as rule 3,
 * one level down. A tick, a cross, a wave and a dashed ring are tellable apart in
 * grayscale, at 20px, on a projector; four coloured discs are not. Nothing here
 * is ever red or green, because the row already says what it is in words.
 *
 * Driven by `agreement`, never by `score`. A very common name agrees weakly
 * without contradicting anything, and a cross there tells the merchant the
 * opposite of the truth.
 */

import type { ReactElement } from 'react'
import { AGREEMENT_LABEL } from '../lib/copy'
import type { Agreement } from '../types'

export interface AgreementMarkProps {
  agreement: Agreement
  /** Edge length in px. Rows use 22; the collapsed agreement line uses 16. */
  size?: number
  /**
   * Pass false where the surrounding text already names the agreement — the
   * collapsed "3 details match" line, where four announcements would be noise.
   */
  labelled?: boolean
}

const STROKE = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2.6,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

function shape(agreement: Agreement): ReactElement {
  switch (agreement) {
    case 'AGREE':
      // a bare tick — no container, so it cannot be confused with a status glyph
      return <path d="M4 12.6 L9.4 18 L20 5.8" {...STROKE} />
    case 'CONTRADICT':
      return (
        <>
          <path d="M5 5 L19 19" {...STROKE} />
          <path d="M19 5 L5 19" {...STROKE} />
        </>
      )
    case 'WEAK':
      // a wave: agrees, but loosely. Nothing else in the set is horizontal.
      return <path d="M3 14.5 c3.5 -6 6.5 -6 9 0 c2.5 6 5.5 6 9 0" {...STROKE} />
    case 'MISSING':
      // a dashed ring: an empty slot, not a failure. Same idea as the NOT FOUND field.
      return (
        <circle cx="12" cy="12" r="9" {...STROKE} strokeDasharray="3.2 3.6" strokeWidth={2.4} />
      )
  }
}

export function AgreementMark({
  agreement,
  size = 22,
  labelled = true,
}: AgreementMarkProps): ReactElement {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className="shrink-0"
      role={labelled ? 'img' : undefined}
      aria-label={labelled ? AGREEMENT_LABEL[agreement] : undefined}
      aria-hidden={labelled ? undefined : true}
      focusable="false"
    >
      {shape(agreement)}
    </svg>
  )
}
