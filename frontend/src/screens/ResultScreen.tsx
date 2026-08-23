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
  /** Leave the verdict and go back to the upload screen. */
  onDismiss: () => void
}

export function ResultScreen({
  result,
  used,
  onUse,
  onDismiss,
}: ResultScreenProps): ReactElement {
  switch (result.status) {
    case 'VERIFIED':
      return <VerdictVerified result={result} used={used} onUse={onUse} onDismiss={onDismiss} />
    case 'UNMATCHED':
      return <VerdictUnmatched result={result} used={used} onUse={onUse} onDismiss={onDismiss} />
    default:
      return <Verdict result={result} used={used} onUse={onUse} onDismiss={onDismiss} />
  }
}
