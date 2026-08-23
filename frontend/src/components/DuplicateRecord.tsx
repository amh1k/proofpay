/**
 * DUPLICATE: the payment this receipt points at, and the fact that it is spent.
 *
 * There is nothing to oppose here — the claimed and received amounts are the
 * SAME, because the transaction is genuine. So this block deliberately does not
 * borrow the mismatch layout:
 *
 *   - no two figures and no "=" between them. One figure, once, because the
 *     money arrived once.
 *   - no tick. Every field agreeing is why this is a duplicate and not a
 *     mismatch, but a tick on a rejection screen contradicts the verdict; the
 *     agreements are stated in words down in the evidence instead.
 *
 * The one thing the merchant actually needs is WHICH earlier order already used
 * it. The API does not carry that yet, so `earlierOrderRef` returns null and the
 * row tells them how to find it rather than naming an order that may not exist.
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
  const earlier = earlierOrderRef(result)

  return (
    <div className="mt-12 short:mt-8">
      <Figure
        cap="This payment arrived once"
        value={formatMoney(amountMinor)}
        capColor={p.support}
        valueColor={p.ink}
        sub={sub}
      />

      <p className="text-lede mt-6 mb-0 font-bold" style={{ color: p.ink }}>
        It has already paid for another order.
      </p>

      <div className="mt-8" style={{ maxWidth: '52ch' }}>
        {reference && <RecordRow label="Transaction" value={reference} p={p} numeric />}
        {sender && <RecordRow label="Sender" value={sender} p={p} />}
        {formatStamp(occurredAt) && (
          <RecordRow label="Arrived" value={formatStamp(occurredAt) ?? ''} p={p} numeric />
        )}
        <RecordRow
          label="Already used for"
          value={earlier ?? EARLIER_ORDER_UNKNOWN}
          p={p}
          numeric={earlier !== null}
          soft={earlier === null}
        />
      </div>
    </div>
  )
}
