/**
 * The thin top strip: brand, reference, timestamp, provider — and the way back.
 *
 * Uppercase, letterspaced, low emphasis. It is chrome. It must never compete with
 * the sign underneath it — if you find yourself wanting to colour it, the answer
 * is no.
 *
 * "Start over" lives here for one reason: this strip is the only thing on screen
 * during all three screens, so a control in it is always reachable — mid-check,
 * mid-verdict, after an error. It is drawn at chrome weight on purpose. Rule 5 is
 * about the two verdict actions, where equal weight is the product refusing to
 * decide for the merchant; this is not one of those, and it must not read like a
 * third answer to the question the sign just asked.
 */

import type { ReactElement } from 'react'
import { formatStamp } from '../lib/time'
import { providerName } from '../lib/copy'

export interface TopStripProps {
  /** e.g. `"ORD-1042"`. Null on the upload screen, where there is nothing to name. */
  reference?: string | null
  /** ISO-8601. When the check ran. Null on the upload screen. */
  checkedAt?: string | null
  /** Raw provider id, e.g. `"jazzcash"`. Null when unknown. */
  provider?: string | null
  /** Clear everything and go back to a clean upload screen. Also bound to Escape. */
  onReset: () => void
}

const HAIRLINE = 'rgba(255,255,255,.16)'
const CHROME_RULE = 'rgba(255,255,255,.32)'

const RESET_LABEL = 'Start over'
const RESET_HINT = 'Start over — clears this check and returns to the upload screen (Esc)'

export function TopStrip({
  reference,
  checkedAt,
  provider,
  onReset,
}: TopStripProps): ReactElement {
  const stamp = formatStamp(checkedAt)

  const parts: string[] = []
  if (reference) parts.push(reference)
  if (stamp) parts.push(`checked ${stamp}`)
  if (provider) parts.push(providerName(provider))

  return (
    <header
      className="cap flex shrink-0 items-center gap-4 border-b-2 px-6 py-2 md:px-12 md:py-4 lg:px-16"
      style={{
        background: 'var(--color-ink)',
        color: 'var(--color-on-field-dim)',
        borderColor: HAIRLINE,
      }}
    >
      <b
        className="shrink-0 font-extrabold"
        style={{ color: 'var(--color-on-field)', letterSpacing: '0.1em' }}
      >
        ProofPay
      </b>

      {/* Doubles as the spacer, so the reference sits beside the control it is
        * least likely to be confused with. `minWidth: 0` inline because the
        * spacing scale has no 0 step and `min-w-0` therefore generates nothing —
        * without it `truncate` cannot shrink and a long reference pushes the
        * reset button off a 360px screen. */}
      <span className="num flex-1 truncate text-right" style={{ minWidth: 0 }}>
        {parts.join(' · ')}
      </span>

      <button
        type="button"
        onClick={onReset}
        title={RESET_HINT}
        aria-label={RESET_HINT}
        className="cap shrink-0 cursor-pointer px-3 py-2"
        style={{
          background: 'transparent',
          border: `2px solid ${CHROME_RULE}`,
          color: 'var(--color-on-field)',
        }}
      >
        {RESET_LABEL}
      </button>
    </header>
  )
}
