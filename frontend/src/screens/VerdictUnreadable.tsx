/**
 * The receipt could not be read. This is not a verdict, and must not look like one.
 *
 * WHY THIS SCREEN EXISTS
 *
 * When the cloud reader fails — a timeout, a rate limit, venue wifi — the
 * extraction service does not raise. It returns an EMPTY claim with
 * `degraded=True` (`extraction/service.py`, the `ExtractionError` branch), and
 * an empty claim has no amount, no reference and no name to match on. The engine
 * does the only correct thing with nothing: no candidate clears retrieval, so it
 * answers UNMATCHED.
 *
 * Which is how the merchant came to be told, in the largest type on the page,
 * "No matching payment yet — transfers can take a few minutes to arrive."
 * Reassuring, confident, and untrue. Their customer paid. Our reader was down.
 *
 * That is the exact failure this product exists to prevent, pointed at ourselves,
 * so a degraded read is intercepted in `ResultScreen` before it can be routed to
 * a verdict at all. A banner above the verdict would not have been enough: the
 * verdict WORD is the biggest thing on the screen, and nothing printed underneath
 * it undoes a wrong one printed that large.
 *
 * The register is rule 4's, turned on ourselves. Say what WE could not do. The
 * merchant did nothing wrong, the customer is not suspected of anything, and the
 * receipt may well be perfectly good. Nothing here is an accusation, so nothing
 * here is coloured like one: paper, dashed rule, and an action that just tries
 * again.
 */

import type { ReactElement } from 'react'
import { UNREADABLE_ADVICE, UNREADABLE_LEDE, UNREADABLE_TITLE } from '../lib/copy'
import { SIGN_CLASS, SIGN_MIN_HEIGHT } from '../lib/sign'
import type { VerificationResult } from '../types'

export interface VerdictUnreadableProps {
  result: VerificationResult
  /** Try the same screenshot again. The reader may be back. */
  onRetry: () => void
  /** Leave it. Nothing was decided, so nothing is left half-done. */
  onDismiss: () => void
}

/* The paper ground, borrowed from NOT FOUND rather than reinvented: this screen
 * is in the same family, the one that accuses nobody. */
const BUTTON = {
  background: 'transparent',
  border: '3px solid var(--color-on-paper)',
  color: 'var(--color-on-paper)',
} as const

const BUTTON_CLASS = 'flex cursor-pointer items-center gap-3 px-8 py-4 text-lg font-bold'

export function VerdictUnreadable({
  result,
  onRetry,
  onDismiss,
}: VerdictUnreadableProps): ReactElement {
  return (
    <section
      className={SIGN_CLASS}
      style={{
        // `--color-notfound`, the white NOT FOUND stands on. There is no
        // `--color-paper` token; naming one that does not exist resolves to
        // nothing, and near-black `--color-on-paper` text then sits on the
        // ink chrome showing through. The screen renders, reads blank, and
        // every text assertion still passes, because the DOM has the words.
        background: 'var(--color-notfound)',
        color: 'var(--color-on-paper)',
        minHeight: SIGN_MIN_HEIGHT,
      }}
    >
      {/* A dashed rule, like NOT FOUND: nothing here is settled. */}
      <div style={{ borderTop: '3px dashed var(--color-rule)', maxWidth: '18ch' }} />

      <h1 className="text-verdict mt-6 mb-0 short:mt-4" style={{ maxWidth: '13ch' }}>
        {UNREADABLE_TITLE}
      </h1>

      <p
        className="text-lede mt-6 mb-0 short:mt-4"
        style={{ color: 'var(--color-on-paper-dim)', maxWidth: '34ch' }}
      >
        {UNREADABLE_LEDE}
      </p>

      <div className="mt-12 flex flex-wrap gap-4 short:mt-6">
        {/* Same weight, no primary — rule 5 holds here as everywhere. Retry is
          * first because it is the thing that usually works. */}
        <button type="button" className={BUTTON_CLASS} style={BUTTON} onClick={onRetry}>
          Try again
        </button>
        <button type="button" className={BUTTON_CLASS} style={BUTTON} onClick={onDismiss}>
          Leave for later
        </button>
      </div>

      <p className="mt-6 mb-0" style={{ color: 'var(--color-on-paper-dim)', maxWidth: '52ch' }}>
        {UNREADABLE_ADVICE}
      </p>

      {/* The reference, small, for anyone who has to report this. Deliberately
        * the only machine-facing thing on the screen. */}
      <p className="cap mt-12 mb-0 short:mt-6" style={{ color: 'var(--color-on-paper-dim)' }}>
        {result.id}
      </p>
    </section>
  )
}
