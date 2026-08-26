/**
 * What this shop already checked.
 *
 * The nav strip has always shown three counts. Until now they were inert — a
 * figure with nothing behind it — which is the one thing a count must never be:
 * a merchant who reads "3" under "Do not approve" and taps it is asking WHICH
 * three, and an app that cannot answer has told them a number it does not stand
 * behind. This screen is that answer.
 *
 *     nav cell  --(tap)-->  this list  --(tap a row)-->  that verdict, replayed
 *
 * The list is built from SUMMARIES, not from whole verifications. A summary
 * carries a status and no reasons, so every row here says
 * `presentation(status).short` and nothing cleverer. `verdictWord()` — which can
 * tell a reused screenshot from a reused transaction — needs the reasons, and a
 * label that changes depending on how much of a record the caller happens to
 * hold is worse than one plain word. Tapping the row fetches the whole thing,
 * and THAT screen says the sharper sentence.
 *
 * Signage register: ink ground like the upload screen and the nav strip, so the
 * app has exactly one dark chrome and the colour on screen is always a verdict.
 * Each row carries its own status colour as a bar down its leading edge — the
 * smallest amount of the verdict's field that still reads across a room, and the
 * glyph beside it repeats the same thing by silhouette for anyone who cannot use
 * the colour.
 */

import type { CSSProperties, ReactElement } from 'react'
import { HISTORY_EMPTY, HISTORY_NO_AMOUNT, HISTORY_TITLE } from '../lib/copy'
import { formatMoney } from '../lib/money'
import { orderRef } from '../lib/orders'
import type { FilterKey } from '../lib/nav'
import { inFilter } from '../lib/nav'
import { presentation, severity } from '../lib/status'
import { formatStamp } from '../lib/time'
import type { Order, VerificationSummary } from '../types'

export interface HistoryScreenProps {
  /** Which cell opened this. Decides the heading and which rows appear. */
  filter: FilterKey
  /** Every check the app knows about, unfiltered. This screen does the filtering. */
  items: VerificationSummary[]
  /**
   * The merchant's orders, used only to name them. A row carries the engine's
   * `order_demo_1002`; the merchant knows it as `ORD-S01`. See `lib/orders.ts` —
   * the top strip translates through the same function, so the two surfaces
   * cannot call one order by two names.
   */
  orders: Order[] | null
  /** Replay one check. The shell fetches the whole verification and shows it. */
  onOpen: (verificationId: string) => void
  /** Set when the list could not be loaded. Render it; do not swallow it. */
  error: string | null
}

/* ── the ink ground ─────────────────────────────────────────────────────────
 * Alphas of white, the same ones `TopStrip` and `UploadScreen` already use. No
 * new hue enters here; the only colour on this screen belongs to a verdict. */
const HAIRLINE = 'rgba(255,255,255,.16)'
const ROW_WASH = 'rgba(255,255,255,.04)'

/** One row. The leading bar is the verdict's field colour, four pixels of it. */
const ROW: CSSProperties = {
  background: ROW_WASH,
  borderBottom: `2px solid ${HAIRLINE}`,
}

export function HistoryScreen({
  filter,
  items,
  orders,
  onOpen,
  error,
}: HistoryScreenProps): ReactElement {
  // Worst first, then newest first inside a severity. A merchant opening "do not
  // approve" wants the duplicate before the mismatch, and today's before
  // yesterday's; `severity` is the same ordering the demo rail already uses, so
  // the two surfaces cannot disagree about which verdict is worse.
  const rows = items
    .filter((item) => inFilter(filter, item.status))
    .sort((a, b) => {
      const bySeverity = severity(a.status) - severity(b.status)
      if (bySeverity !== 0) return bySeverity
      return (b.created_at ?? '').localeCompare(a.created_at ?? '')
    })

  return (
    <section
      className="flex flex-1 flex-col gap-6 overflow-y-auto px-6 py-8 short:gap-4 short:py-6 md:px-12 lg:px-16"
      style={{ background: 'var(--color-ink)', color: 'var(--color-on-field)' }}
    >
      <h1 className="text-lede m-0 font-bold" style={{ maxWidth: '24ch' }}>
        {HISTORY_TITLE[filter]}
      </h1>

      {error !== null && (
        <p
          role="alert"
          className="text-lede m-0"
          style={{ color: 'var(--color-pale-red)', maxWidth: '40ch' }}
        >
          {error}
        </p>
      )}

      {error === null && rows.length === 0 && (
        <p className="text-lede m-0" style={{ color: 'var(--color-on-field-dim)', maxWidth: '34ch' }}>
          {HISTORY_EMPTY[filter]}
        </p>
      )}

      {rows.length > 0 && (
        <ul className="m-0 flex list-none flex-col p-0">
          {rows.map((row) => {
            // Rule 3: the word, the colour and the glyph all come through the one
            // lookup. Nothing on this row is chosen by naming a status.
            const look = presentation(row.status)
            const Glyph = look.Glyph
            const stamp = formatStamp(row.created_at)

            return (
              <li key={row.id}>
                <button
                  type="button"
                  onClick={() => onOpen(row.id)}
                  className="flex w-full cursor-pointer items-center gap-4 px-4 py-4 text-left"
                  style={{ ...ROW, borderLeft: `4px solid ${look.field}` }}
                >
                  <Glyph size={32} />

                  {/* `minWidth: 0` inline, not `min-w-0`: the spacing scale has no
                    * 0 step, so that utility generates nothing — and without it a
                    * long order reference refuses to shrink and pushes the figure
                    * off the row. */}
                  <span className="flex flex-1 flex-col" style={{ minWidth: 0 }}>
                    <b className="block text-lg font-bold">{look.short}</b>
                    <span
                      className="cap block truncate"
                      style={{ color: 'var(--color-on-field-dim)' }}
                    >
                      {orderRef(orders, row.order_id) ?? '—'}
                    </span>
                  </span>

                  <span className="flex shrink-0 flex-col items-end">
                    <b className="num block text-lg font-bold">
                      {row.amount_minor === null
                        ? ''
                        : formatMoney(row.amount_minor, row.currency)}
                    </b>
                    <span className="cap block" style={{ color: 'var(--color-on-field-dim)' }}>
                      {row.amount_minor === null ? HISTORY_NO_AMOUNT : (stamp ?? '')}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
