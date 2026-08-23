/**
 * The two amounts, side by side on a shared baseline.
 *
 * This is the centre of the mismatch sign and the thing a judge remembers:
 * Rs 5,000 struck through, Rs 500 at full strength, and one line naming the gap.
 *
 * What it renders is decided by the DATA, not by the status:
 *
 *   claimed ≠ received   two figures, the claimed one struck, plus the delta
 *   claimed = received   ONE figure. Never two equal numbers, never an "=" —
 *                        two identical figures with a symbol between them is a
 *                        sum, and a sum on a verdict screen reads as a tick.
 *   received unknown     the claimed figure and a dashed, empty slot
 *
 * DUPLICATE and NEEDS_REVIEW do not use this at all: on those screens there is
 * nothing to oppose, so they have their own blocks.
 */

import type { ReactElement } from 'react'
import { Figure, DashedCell } from './Figure'
import { providerName } from '../lib/copy'
import { amountGap, formatMoney } from '../lib/money'
import type { StatusPresentation } from '../lib/status'
import { formatClock } from '../lib/time'
import { deltaLine } from '../lib/verdict'

export interface AmountDuelProps {
  p: StatusPresentation
  claimedMinor: number | null
  receivedMinor: number | null
  /** Raw provider id of the transaction that arrived, e.g. `"jazzcash"`. */
  provider?: string | null
  /** ISO-8601 — when the money actually landed. */
  receivedAt?: string | null
}

const CLAIMED_CAP = 'Claimed on the screenshot'
const RECEIVED_CAP = 'Received in your account'

export function AmountDuel({
  p,
  claimedMinor,
  receivedMinor,
  provider = null,
  receivedAt = null,
}: AmountDuelProps): ReactElement {
  const gap = amountGap(claimedMinor, receivedMinor)
  const delta = deltaLine(gap)

  const clock = formatClock(receivedAt)
  const sub = receivedMinor === null ? null : [providerName(provider), clock].filter(Boolean).join(', ')

  // The two agree, so there is only one fact: the money that arrived.
  if (gap && gap.direction === 'EQUAL') {
    return (
      <div className="mt-12 short:mt-8">
        <Figure
          cap={RECEIVED_CAP}
          value={formatMoney(receivedMinor)}
          capColor={p.support}
          valueColor={p.ink}
          sub={sub}
        />
      </div>
    )
  }

  return (
    <div className="mt-12 short:mt-8">
      {/* Stacked on a phone, side by side from `md` up.
          Not `flex-wrap` alone: at 360px the two captions would each fold onto
          three lines and the figures would still sit in one cramped row. Below
          `md` the two amounts get the full width and stay the largest thing on
          the screen, which is the whole point of the sign.

          items-start, not items-end: the two captions are one line each, so the
          figures land on a shared baseline — and the received side's provider
          line hangs below it instead of pushing the whole column up. */}
      <div className="flex flex-col gap-8 md:flex-row md:flex-wrap md:items-start md:gap-12">
        {claimedMinor !== null && (
          <Figure
            cap={CLAIMED_CAP}
            value={formatMoney(claimedMinor)}
            capColor={p.support}
            valueColor={p.support}
            struck={receivedMinor !== null}
            sub={receivedMinor === null ? 'from the screenshot' : null}
          />
        )}

        {receivedMinor === null ? (
          <DashedCell
            cap={RECEIVED_CAP}
            value="Nothing yet"
            capColor={p.support}
            valueColor={p.ink}
            rule={p.rule}
          />
        ) : (
          <Figure
            cap={RECEIVED_CAP}
            value={formatMoney(receivedMinor)}
            capColor={p.support}
            valueColor={p.ink}
            sub={sub}
          />
        )}
      </div>

      {delta && (
        <p className="text-lede mt-6 mb-0 font-bold short:mt-4" style={{ color: p.ink }}>
          {delta}
        </p>
      )}
    </div>
  )
}
