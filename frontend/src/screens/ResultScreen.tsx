/**
 * The result screen, as the shell knows it.
 *
 * This file is the name `App.tsx` imports and one routing decision, so the
 * shell's props never have to move. Nothing else belongs here — no sign, no
 * facts, no actions.
 *
 * The one decision: the three REJECTIONS are `Verdict.tsx`; the two verdicts that
 * are not accusations are `VerdictPositive.tsx`. They share every component, so
 * this is not two designs — it is one design with two things that only the
 * non-negative pair needs. NOT FOUND must never offer an approve action (rule 4)
 * and has to say what was searched, and VERIFIED has to explain what "Use it"
 * spends. Routing it here keeps `Verdict`'s status switch about FACTS, which is
 * the only thing it should ever switch on.
 */

import type { ReactElement } from 'react'
import { Verdict } from './Verdict'
import { VerdictUnmatched, VerdictVerified } from './VerdictPositive'
import { VerdictUnreadable } from './VerdictUnreadable'
import type { VerificationResult } from '../types'

export interface ResultScreenProps {
  result: VerificationResult
  /**
   * True once this payment has been marked used. This is the memory that catches
   * the same genuine receipt being sent a second time, so it must survive the
   * screen: the shell owns it, not this component.
   */
  used: boolean
  /** The merchant tapped "Use it". Spend the matched transaction. */
  onUse: (result: VerificationResult) => void
  /**
   * Run the same check again. Only reachable from the unreadable screen, where
   * nothing was decided and the reader may simply be back.
   */
  onRetry: () => void
  /** Leave the verdict and go back to the upload screen. */
  onDismiss: () => void
}

export function ResultScreen({
  result,
  used,
  onUse,
  onRetry,
  onDismiss,
}: ResultScreenProps): ReactElement {
  // A degraded read is intercepted BEFORE the status switch, because in that
  // state the status is not an answer. When the cloud reader fails, extraction
  // returns an empty claim rather than raising, and an empty claim matches
  // nothing, so the engine correctly answers UNMATCHED about nothing. Routed to
  // a verdict, that reads "No matching payment yet" in the largest type on the
  // page: reassuring, confident, and wrong, because the customer did pay and it
  // was our reader that was down. See `VerdictUnreadable`.
  if (result.degraded) {
    return <VerdictUnreadable result={result} onRetry={onRetry} onDismiss={onDismiss} />
  }

  switch (result.status) {
    case 'VERIFIED':
      return <VerdictVerified result={result} used={used} onUse={onUse} onDismiss={onDismiss} />
    case 'UNMATCHED':
      return <VerdictUnmatched result={result} used={used} onUse={onUse} onDismiss={onDismiss} />
    default:
      return <Verdict result={result} used={used} onUse={onUse} onDismiss={onDismiss} />
  }
}
