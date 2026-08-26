/**
 * DUPLICATE: the payment this receipt points at, and the fact that it is spent.
 *
 * There is nothing to oppose here. On a reused TRANSACTION the claimed and
 * received amounts are the SAME, because the transaction is genuine; on a reused
 * SCREENSHOT no transaction is named at all, because `R025` decides on the image
 * bytes and never looks at the ranking (`Rule.reads_ranking`), so every figure
 * below falls back to what the picture itself says. Either way there is one
 * number, not two, and this block deliberately does not borrow the mismatch
 * layout:
 *
 *   - no two figures and no "=" between them. One figure, once, because the
 *     money arrived once.
 *   - no tick. Every field agreeing is why this is a duplicate and not a
 *     mismatch, but a tick on a rejection screen contradicts the verdict; the
 *     agreements are stated in words down in the evidence instead.
 *
 * The one thing the merchant actually needs is WHICH earlier order already used
 * it, and whether they get it now depends on which duplicate this is. On
 * screenshot reuse the engine knows and says so, so the row names the order. On
 * an allocated transaction it still only knows the payment is spent, not what
 * spent it, so `earlierOrderRef` returns null and the row tells them how to find
 * it rather than naming an order that may not exist.
 *
 * The two also need different words, and this is the screen where the difference
 * is most visible. "It has already paid for another order" is true of a reused
 * TRANSACTION. On a reused SCREENSHOT the transaction may never have been
 * claimed by anyone — what repeated is the picture — so the lede and the row
 * label both switch. See the `PROOF_REUSED` branch in `lib/copy.ts`.
 */

import type { ReactElement } from 'react'
import { Figure } from './Figure'
import { providerName } from '../lib/copy'
import { formatMoney } from '../lib/money'
import type { StatusPresentation } from '../lib/status'
import { formatClock, formatStamp } from '../lib/time'
import { EARLIER_ORDER_UNKNOWN, earlierOrderRef } from '../lib/verdict'
import type { VerificationResult } from '../types'

export interface DuplicateRecordProps {
  p: StatusPresentation
  result: VerificationResult
}

interface RecordRowProps {
  label: string
  value: string
  p: StatusPresentation
  /** Ids, figures and clock times. Rule 7. */
  numeric?: boolean
  /** True when the value is a sentence we are inferring, not a record we hold. */
  soft?: boolean
}

function RecordRow({ label, value, p, numeric = false, soft = false }: RecordRowProps): ReactElement {
  return (
    <div className="flex flex-wrap items-baseline gap-4 py-3" style={{ borderTop: `2px solid ${p.support}` }}>
      <span className="cap" style={{ color: p.support, minWidth: '15ch' }}>
        {label}
      </span>
      <span
        className={numeric ? 'num text-lg font-bold' : 'text-lg font-bold'}
        style={{ color: soft ? p.support : p.ink, fontWeight: soft ? 400 : 700 }}
      >
        {value}
      </span>
    </div>
  )
}

export function DuplicateRecord({ p, result }: DuplicateRecordProps): ReactElement {
  const txn = result.matched_transaction
  const amountMinor = txn?.amount_minor ?? result.claim.amount_minor
  const reference = txn?.id ?? result.claim.reference_id
  const sender = txn?.sender_name ?? result.claim.sender_name
  const provider = txn?.provider ?? result.claim.provider
  const occurredAt = txn?.occurred_at ?? result.claim.occurred_at

  const clock = formatClock(occurredAt)
  const sub = [providerName(provider), clock].filter(Boolean).join(', ')
  const reused = result.reasons.includes('PROOF_REUSED')
  // Only a verdict ABOUT the screenshot may fill this row from the note that
  // names the screenshot's earlier order. See `earlierOrderRef`, which enforces
  // it; the label below is gated on the same fact so the two can never say
  // different things.
  const earlier = earlierOrderRef(result)

  return (
    <div className="mt-12 short:mt-8">
      <Figure
        cap={reused ? 'The screenshot shows' : 'This payment arrived once'}
        value={formatMoney(amountMinor)}
        capColor={p.support}
        valueColor={p.ink}
        sub={sub}
      />

      <p className="text-lede mt-6 mb-0 font-bold" style={{ color: p.ink }}>
        {reused
          ? 'This same screenshot was sent for another order.'
          : 'It has already paid for another order.'}
      </p>

      <div className="mt-8" style={{ maxWidth: '52ch' }}>
        {reference && <RecordRow label="Transaction" value={reference} p={p} numeric />}
        {sender && <RecordRow label="Sender" value={sender} p={p} />}
        {formatStamp(occurredAt) && (
          <RecordRow label="Arrived" value={formatStamp(occurredAt) ?? ''} p={p} numeric />
        )}
        <RecordRow
          label={reused ? 'Same screenshot as' : 'Already used for'}
          value={earlier ?? EARLIER_ORDER_UNKNOWN}
          p={p}
          numeric={earlier !== null}
          soft={earlier === null}
        />
      </div>
    </div>
  )
}
