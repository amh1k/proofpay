/**
 * The two actions under a verdict.
 *
 * Rule 5, made structural: this component takes a TUPLE of exactly two actions
 * and renders both through the same code path, with the same border, padding and
 * type. There is no `primary` prop and no place to put one. "Do not approve"
 * drawn louder than "Approve anyway" is the product making the merchant's
 * decision for them, and that is the one thing it must never do.
 *
 * Borders are 3px in the field's rule colour, backgrounds transparent, focus is
 * the global 3px `currentColor` outline from `theme.css`. No `outline: none`
 * anywhere, and no transition.
 */

import type { ReactElement } from 'react'
import type { StatusPresentation } from '../lib/status'

export interface VerdictAction {
  label: string
  onClick: () => void
  /** Spent already — the button stays in place and stays readable. */
  disabled?: boolean
}

/** Exactly two, always. A verdict with one button is a verdict with no choice. */
export type ActionPair = readonly [VerdictAction, VerdictAction]

export interface VerdictActionsProps {
  p: StatusPresentation
  actions: ActionPair
}

export function VerdictActions({ p, actions }: VerdictActionsProps): ReactElement {
  return (
    <div className="mt-12 flex flex-wrap gap-4 short:mt-6">
      {actions.map((action) => (
        <button
          key={action.label}
          type="button"
          onClick={action.onClick}
          disabled={action.disabled}
          className="px-8 py-4 text-lg font-bold"
          style={{
            background: 'transparent',
            border: `3px solid ${p.rule}`,
            color: p.ink,
            opacity: action.disabled ? 0.6 : 1,
            cursor: action.disabled ? 'not-allowed' : 'pointer',
          }}
        >
          {action.label}
        </button>
      ))}
    </div>
  )
}
