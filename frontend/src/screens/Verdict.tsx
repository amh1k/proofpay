/**
 * THE verdict screen — the three REJECTIONS.
 *
 *   SUSPICIOUS    the amount on the picture is not the amount that arrived
 *   DUPLICATE     the payment is real, and an earlier order already spent it
 *   NEEDS_REVIEW  two payments could be this one, and neither has been chosen
 *
 * VERIFIED and NOT FOUND are `VerdictPositive.tsx`; `ResultScreen` routes. They
 * share every component in this folder, so this is one design, not two.
 *
 * It is a SIGN, not a card. A full-bleed field in the status colour, one very
 * large word, one shape, and nothing else competing with them — read from six
 * metres, in a bright room, off a projector. The detail lives below the fold, so
 * the merchant who wants it scrolls and the room never has to.
 *
 *   ┌──────────────────────────────────────────┐  ← TopStrip (App shell)
 *   │  ▲                                       │
 *   │  Amount does not match                   │
 *   │  The screenshot claims Rs 5,000, but…    │
 *   │                                          │
 *   │  CLAIMED             RECEIVED            │  two figures, shared baseline
 *   │  R̶s̶ ̶5̶,̶0̶0̶0̶            Rs 500               │
 *   │  Rs 4,500 short of the order total       │
 *   │                                          │
 *   │  [ Do not approve ]  [ Approve anyway ]  │  identical weight, always
 *   ├── the fold ──────────────────────────────┤
 *   │  the evidence, worst row first           │
 *   │  ✓ Transaction ID · ✓ Time · ✓ Sender    │  never deleted
 *   │  SEND THIS BACK ON WHATSAPP              │
 *   └──────────────────────────────────────────┘  ← NavStrip (App shell)
 *
 * Every colour, word and glyph comes from `presentation()` and `verdictCopy()`.
 * There is no hex code in this file and no switch on status that decides what
 * something LOOKS like — the only status switch picks which BLOCK OF FACTS a
 * verdict has to show, because a mismatch has two opposed amounts, a duplicate
 * has one spent payment, and an ambiguous result has neither.
 *
 * Never renders `confidence`. Never renders `risk`.
 */

import type { ReactElement } from 'react'
import { AmountDuel } from '../components/AmountDuel'
import { CandidatePair } from '../components/CandidatePair'
import { DuplicateRecord } from '../components/DuplicateRecord'
import { EvidenceList } from '../components/EvidenceList'
import { ReplyBlock } from '../components/ReplyBlock'
import { VerdictActions, type ActionPair } from '../components/VerdictActions'
import { providerName, verdictCopy } from '../lib/copy'
import { evidenceRows } from '../lib/evidence'
import { SIGN_CLASS, SIGN_MIN_HEIGHT } from '../lib/sign'
import { presentation, type StatusPresentation } from '../lib/status'
import { agreementMeaning } from '../lib/verdict'
import type { VerificationResult } from '../types'

export interface VerdictProps {
  result: VerificationResult
  /** True once this payment has been marked used. The shell owns this memory. */
  used: boolean
  /** The merchant approved. Spend the matched transaction so a repeat is caught. */
  onUse: (result: VerificationResult) => void
  /** Leave the verdict, back to the upload screen. */
  onDismiss: () => void
}

/** The block of facts this verdict has to show. The only status switch on the screen. */
function factBlock(result: VerificationResult, look: StatusPresentation): ReactElement {
  switch (result.status) {
    case 'DUPLICATE':
      // Claimed and received are the SAME here — the transaction is genuine.
      // Nothing to oppose, so nothing is opposed: one figure, and the earlier
      // order that already spent it. No "=", no tick on a rejection.
      return <DuplicateRecord p={look} result={result} />

    case 'NEEDS_REVIEW':
      // `matched_txn_id` is null on purpose. Two empty slots, neither chosen.
      return <CandidatePair p={look} result={result} />

    default:
      return (
        <AmountDuel
          p={look}
          claimedMinor={result.claim.amount_minor}
          receivedMinor={result.matched_transaction?.amount_minor ?? null}
          provider={result.matched_transaction?.provider ?? result.claim.provider}
          receivedAt={result.matched_transaction?.occurred_at ?? null}
        />
      )
  }
}

/**
 * What to say where the merchant's record has no value.
 *
 * Not the same as a blank on the screenshot side. `NOT_SHOWN` means the OCR could
 * not read it; this means there is no single transaction to read it FROM, because
 * the engine refused to choose between two.
 */
function recordedFallback(result: VerificationResult): string {
  if (result.matched_transaction) return 'not in this transaction'
  if (result.status === 'NEEDS_REVIEW') return 'no payment chosen yet'
  return 'no payment found yet'
}

export function Verdict({ result, used, onUse, onDismiss }: VerdictProps): ReactElement {
  const look = presentation(result.status)
  const copy = verdictCopy(result)
  const where = providerName(result.matched_transaction?.provider ?? result.claim.provider)
  const meaning = agreementMeaning(result)

  /**
   * Approving is one act: spend the transaction, then go back for the next
   * customer. On a rejection it is the SECOND action and reads "Approve anyway" —
   * a deliberate override, which the merchant is allowed to make and which still
   * has to be remembered, or the same receipt walks in again this afternoon.
   *
   * Rule 5: which one it is changes nothing about how either is drawn.
   */
  const approve = (): void => {
    onUse(result)
    onDismiss()
  }

  const actions: ActionPair = look.approvable
    ? [
        { label: used ? 'Already used' : copy.actions.first, onClick: approve, disabled: used },
        { label: copy.actions.second, onClick: onDismiss },
      ]
    : [
        { label: copy.actions.first, onClick: onDismiss },
        { label: copy.actions.second, onClick: approve },
      ]

  return (
    <section
      className={SIGN_CLASS}
      style={{ background: look.field, color: look.ink, minHeight: SIGN_MIN_HEIGHT }}
    >
      <look.Glyph size={56} />

      <h1 className="text-verdict mt-6 mb-0 short:mt-4" style={{ maxWidth: '13ch' }}>
        {look.word}
      </h1>

      <p className="text-lede mt-6 mb-0 short:mt-4" style={{ color: look.support, maxWidth: '32ch' }}>
        {copy.lede}
      </p>

      {factBlock(result, look)}

      <VerdictActions p={look} actions={actions} />

      <div className="mt-12">
        <EvidenceList
          rows={evidenceRows(result)}
          look={look}
          title={`Checked against your ${where} record`}
          collapse
          recordedFallback={recordedFallback(result)}
        />

        {/* What the ticks mean on a screen that says no. Without this line a
            row of ticks under a rejection reads as a contradiction. */}
        {meaning && (
          <p className="mt-4 text-lg" style={{ color: look.support, maxWidth: '56ch' }}>
            {meaning}
          </p>
        )}
      </div>

      <ReplyBlock p={look} reply={copy.reply} advice={copy.advice} />
    </section>
  )
}
