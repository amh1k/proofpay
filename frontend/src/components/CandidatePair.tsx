/**
 * NEEDS_REVIEW: two payments could be this one, and neither has been chosen.
 *
 * `matched_txn_id` is null here ON PURPOSE — the engine refused to pick, because
 * naming one of two equally good candidates hands the merchant the wrong payment
 * to allocate. So this block must not quietly pick either. It renders the
 * refusal: two empty dashed slots, side by side, identical, neither filled.
 *
 * Both cells are empty rather than populated because the API carries no candidate
 * list yet — only the fact that there was more than one. Every word underneath is
 * derived from the evidence rows: the fields that AGREED are exactly the fields
 * that failed to separate the two, and the field that is MISSING is the one that
 * would have settled it. When the API grows a candidate list, fill the cells with
 * it; do not fill them from the claim.
 */

import type { ReactElement } from 'react'
import { DashedCell, Figure } from './Figure'
import { formatMoney } from '../lib/money'
import type { StatusPresentation } from '../lib/status'
import { separatorSentence, sharedFieldsSentence } from '../lib/verdict'
import type { VerificationResult } from '../types'

export interface CandidatePairProps {
  p: StatusPresentation
  result: VerificationResult
}

/** Two slots, because two payments matched. Not a list — a refusal to choose. */
const SLOTS = ['Payment 1', 'Payment 2'] as const

export function CandidatePair({ p, result }: CandidatePairProps): ReactElement {
  const claimed = result.claim.amount_minor
  const shared = sharedFieldsSentence(result.evidence)
  const separator = separatorSentence(result.evidence)

  return (
    <div className="mt-12 short:mt-8">
      {claimed !== null && (
        <Figure
          cap="Claimed on the screenshot"
          value={formatMoney(claimed)}
          capColor={p.support}
          valueColor={p.ink}
          sub="from the screenshot"
        />
      )}

      <div className="mt-8">
        <div className="cap" style={{ color: p.support }}>
          Which payment this is
        </div>
        <div className="mt-3 flex flex-wrap gap-6">
          {SLOTS.map((slot) => (
            <div key={slot} style={{ flex: '1 1 220px' }}>
              <DashedCell
                cap={slot}
                value="Not chosen"
                capColor={p.support}
                valueColor={p.ink}
                rule={p.rule}
              />
            </div>
          ))}
        </div>
      </div>

      {(shared || separator) && (
        <p className="text-lede mt-6 mb-0" style={{ color: p.ink, maxWidth: '46ch' }}>
          {shared} {separator}
        </p>
      )}
    </div>
  )
}
