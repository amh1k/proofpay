/**
 * What the merchant sends back on WhatsApp.
 *
 * The last copy rule: a verdict the merchant cannot act on wasted their time.
 * This is the last thing the sign says because it is the last thing they do
 * before serving the next customer — the sentence to send, and under it the one
 * line of advice about the order itself.
 *
 * The words are `verdictCopy(result).reply` and `.advice`; not one of them is
 * written here. Every colour comes from `presentation(result.status)`, which is
 * how the same block sits on a red field, a green one and the NOT FOUND paper
 * without ever choosing a colour.
 *
 * Shared by every verdict family, so the five screens end the same way.
 *
 * Added for the verdict screens; not a foundation file.
 */

import type { ReactElement } from 'react'
import type { StatusPresentation } from '../lib/status'

export interface ReplyBlockProps {
  /** From `presentation(result.status)`. */
  p: StatusPresentation
  /** From `verdictCopy(result).reply`. */
  reply: string
  /** From `verdictCopy(result).advice`. */
  advice: string
  /** The caption above it. */
  label?: string
}

export function ReplyBlock({
  p,
  reply,
  advice,
  label = 'What to say back',
}: ReplyBlockProps): ReactElement {
  return (
    <div
      className="mt-12 pt-6"
      style={{ borderTop: `2px ${p.dashed ? 'dashed' : 'solid'} ${p.support}` }}
    >
      <div className="cap" style={{ color: p.support }}>
        {label}
      </div>
      <p className="mt-3 mb-0 text-lg" style={{ color: p.ink, maxWidth: '56ch' }}>
        &ldquo;{reply}&rdquo;
      </p>
      <p className="mt-2 mb-0" style={{ color: p.support, maxWidth: '56ch' }}>
        {advice}
      </p>
    </div>
  )
}
