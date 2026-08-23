/**
 * The two verdicts that are not accusations: VERIFIED and NOT FOUND.
 *
 * They are one file because they are one idea seen from two sides, and because
 * what separates them from the three rejections is not a colour — it is that
 * neither is a charge against the customer. Set side by side you can check it: a
 * deep green field with one confirmed figure and a spend action, against white
 * paper with a dashed rule, a hollow clock, and no approve action anywhere on it.
 *
 * The layout, the amount block, the action pair, the evidence and the reply seam
 * are the SAME components the three rejections use (`AmountDuel`,
 * `VerdictActions`, `EvidenceList`, `ReplyBlock`). Five screens, one system —
 * that is the only way a room reads the difference between them as meaning
 * something. What is written here is only what these two states need and the
 * others do not.
 *
 * VERIFIED
 *   `AmountDuel` collapses to ONE figure when the two amounts agree, which is
 *   exactly right: confirmed money is a single number, and at six metres "one
 *   figure" reads as a different screen from "two figures" before the colour has
 *   registered (rule 2).
 *
 *   "Use it" is the whole of duplicate detection. It spends the matched
 *   transaction, so the same genuine receipt sent again this afternoon comes back
 *   as ALREADY COUNTED. It earns its prominence from position and from the line
 *   under it that says what a tap does — never from extra visual weight, because
 *   rule 5 holds on every screen.
 *
 * NOT FOUND (rule 4 — the state most products lie about)
 *   No fill, no colour, dashed rules, hollow glyph, and copy in the register of
 *   what WE know: nothing matching has arrived YET. Three things this screen has
 *   that no other verdict does:
 *
 *     - The evidence list is the RECEIPT'S OWN fields, with no marks. Nothing was
 *       compared, so nothing gets a tick or a cross — and reading the fields back
 *       is what lets the merchant go and look in their feed themselves.
 *     - It says what was searched, out loud. A screen that says "not found"
 *       without saying where it looked is asking to be taken on faith.
 *     - Its actions are "Check again" and "Leave for later" — the only verdict in
 *       the app with no approve action of any kind. "Approve anyway" is right on a
 *       mismatch, where the merchant may know something we do not; here there is
 *       nothing to know yet. A payment that has not arrived is not a judgement
 *       call to be nudged into; it is a wait. The words are in `ACTIONS.UNMATCHED`
 *       in `lib/copy.ts` with every other verdict's pair, not local to this file.
 *
 * Neither screen renders `confidence` or `risk`. Rule 1.
 */

import type { ReactElement } from 'react'
import { AmountDuel } from '../components/AmountDuel'
import { EvidenceList } from '../components/EvidenceList'
import { ReplyBlock } from '../components/ReplyBlock'
import { VerdictActions, type ActionPair } from '../components/VerdictActions'
import { providerName, verdictCopy } from '../lib/copy'
import { claimRows, evidenceRows } from '../lib/evidence'
import { searchedSentence } from '../lib/searched'
import { SIGN_CLASS, SIGN_MIN_HEIGHT } from '../lib/sign'
import { presentation, type StatusPresentation } from '../lib/status'
import type { VerificationResult } from '../types'

export interface VerdictPositiveProps {
  result: VerificationResult
  /** True once this payment has been marked used. The shell owns this memory. */
  used: boolean
  /** The merchant tapped "Use it". Spend the matched transaction. */
  onUse: (result: VerificationResult) => void
  /** Leave the verdict and go back to the upload screen. */
  onDismiss: () => void
  /**
   * NOT FOUND's "Check again". Falls back to `onDismiss` — the upload screen is
   * where a re-check starts today. Give it a real re-run at the API stage.
   */
  onRecheck?: () => void
  /**
   * How many payments were actually scanned, for the "what we searched" line.
   * Null — the default — leaves the number out of the sentence rather than
   * inventing one. See `lib/searched.ts`.
   */
  searchedCount?: number | null
}


/** Glyph, the one very large word, the sentence, and an optional reassurance. */
function SignHead({
  p,
  lede,
  note,
}: {
  p: StatusPresentation
  lede: string
  note?: string | null
}): ReactElement {
  return (
    <>
      <p.Glyph size={56} />

      <h1 className="text-verdict mt-6 mb-0 short:mt-4" style={{ maxWidth: '13ch' }}>
        {p.word}
      </h1>

      <p className="text-lede mt-6 mb-0 short:mt-4" style={{ color: p.support, maxWidth: '32ch' }}>
        {lede}
      </p>

      {note != null && note.length > 0 && (
        <p className="mt-3 mb-0" style={{ color: p.support, maxWidth: '46ch' }}>
          {note}
        </p>
      )}
    </>
  )
}

/* ── VERIFIED ──────────────────────────────────────────────────────────────── */

export function VerdictVerified({
  result,
  used,
  onUse,
  onDismiss,
}: VerdictPositiveProps): ReactElement {
  const p = presentation(result.status)
  const copy = verdictCopy(result)
  const matched = result.matched_transaction
  const where = providerName(matched?.provider ?? result.claim.provider)

  /**
   * There is nothing to spend without a transaction to spend, so the button says
   * so rather than lying about what a tap does. It cannot happen on a VERIFIED
   * result from the engine; it can happen to whoever wires this up next.
   */
  const spendable = result.matched_txn_id !== null
  const disabled = used || !spendable

  const approve = (): void => {
    onUse(result)
    onDismiss()
  }

  const actions: ActionPair = [
    { label: used ? 'Already used' : copy.actions.first, onClick: approve, disabled },
    { label: copy.actions.second, onClick: onDismiss },
  ]

  let note: string
  if (!spendable) {
    note = 'There is no transaction on this check to mark as used.'
  } else if (used) {
    note =
      'Already marked used. If this same receipt is sent again it will come back as already counted.'
  } else {
    note = 'Use it marks this payment as spent, so the same receipt cannot be counted twice.'
  }

  return (
    <section
      className={SIGN_CLASS}
      style={{ background: p.field, color: p.ink, minHeight: SIGN_MIN_HEIGHT }}
    >
      <SignHead p={p} lede={copy.lede} note={copy.note} />

      <AmountDuel
        p={p}
        claimedMinor={result.claim.amount_minor}
        receivedMinor={matched?.amount_minor ?? null}
        provider={matched?.provider ?? result.claim.provider}
        receivedAt={matched?.occurred_at ?? null}
      />

      <VerdictActions p={p} actions={actions} />

      <p className="mt-4 mb-0" style={{ color: p.support, maxWidth: '60ch' }}>
        {note}
      </p>

      {/* Everything agreed, so it folds to one line — and the fields are still
          named on it, because "all 4 details match" without them is a score. */}
      <div className="mt-12">
        <EvidenceList
          rows={evidenceRows(result)}
          look={p}
          title={`Checked against your ${where} record`}
          collapse
        />
      </div>

      <ReplyBlock p={p} reply={copy.reply} advice={copy.advice} />
    </section>
  )
}

/* ── NOT FOUND ─────────────────────────────────────────────────────────────── */

export function VerdictUnmatched({
  result,
  onDismiss,
  onRecheck,
  searchedCount = null,
}: VerdictPositiveProps): ReactElement {
  const p = presentation(result.status)
  const copy = verdictCopy(result)

  // "Check again" and "Leave for later", from the one table that owns the words.
  // Neither calls `onUse`; rule 4 allows no approve action on this screen at all.
  const actions: ActionPair = [
    { label: copy.actions.first, onClick: onRecheck ?? onDismiss },
    { label: copy.actions.second, onClick: onDismiss },
  ]

  return (
    <section
      className={SIGN_CLASS}
      style={{ background: p.field, color: p.ink, minHeight: SIGN_MIN_HEIGHT }}
    >
      <SignHead p={p} lede={copy.lede} note={copy.note} />

      {/* The claimed figure beside an empty dashed slot: waiting, not accusing. */}
      <AmountDuel
        p={p}
        claimedMinor={result.claim.amount_minor}
        receivedMinor={null}
        provider={result.claim.provider}
      />

      <VerdictActions p={p} actions={actions} />

      {/* One-sided rows, no marks: nothing was compared, so nothing is judged. */}
      <div className="mt-12">
        <EvidenceList
          rows={claimRows(result)}
          look={p}
          title="What the receipt shows"
          marks={false}
        />
      </div>

      <div className="mt-12 pt-6" style={{ borderTop: `2px dashed ${p.rule}` }}>
        <div className="cap" style={{ color: p.support }}>
          What we searched
        </div>
        <p className="mt-3 mb-0 text-lg" style={{ maxWidth: '56ch' }}>
          {searchedSentence(result, searchedCount)}
        </p>
      </div>

      <ReplyBlock p={p} reply={copy.reply} advice={copy.advice} />
    </section>
  )
}
