/**
 * One money figure on the sign: a small letterspaced caption, and under it a
 * figure at `text-figure` with tabular, slashed-zero numerals (rule 7).
 *
 * The struck variant is the CLAIMED side of a mismatch: muted, ruled through at
 * 4px so the line survives a projector. It is a property of the figure, not of a
 * colour, so a claim can never quietly render at full strength.
 */

import type { CSSProperties, ReactElement } from 'react'

export interface FigureProps {
  /** e.g. "Claimed on the screenshot". Rendered in `cap`. */
  cap: string
  /** Already formatted — `formatMoney`, never a raw paisa count. */
  value: string
  capColor: string
  valueColor: string
  /** True for the claimed side of a mismatch. */
  struck?: boolean
  /** e.g. "JazzCash, 15:42". Optional second line under the figure. */
  sub?: string | null
}

export function Figure({
  cap,
  value,
  capColor,
  valueColor,
  struck = false,
  sub = null,
}: FigureProps): ReactElement {
  const struckStyle: CSSProperties = struck
    ? { textDecorationLine: 'line-through', textDecorationThickness: '4px' }
    : {}

  return (
    <div>
      <div className="cap" style={{ color: capColor }}>
        {cap}
      </div>
      <div className="text-figure num mt-3" style={{ color: valueColor, ...struckStyle }}>
        {value}
      </div>
      {sub && (
        <div className="mt-3 text-sm" style={{ color: capColor }}>
          {sub}
        </div>
      )}
    </div>
  )
}

export interface DashedCellProps {
  cap: string
  /** The one short line inside the cell, e.g. "Nothing yet". */
  value: string
  capColor: string
  valueColor: string
  rule: string
  /** Optional line under the value, at low emphasis. */
  sub?: string | null
}

/**
 * A slot with nothing in it: dashed outline, no fill, no colour of its own.
 *
 * Used where a figure is genuinely unknown — no payment has arrived, or two
 * payments could be the one and neither has been chosen. An empty outline says
 * "not decided". A number here would be an invention.
 */
export function DashedCell({
  cap,
  value,
  capColor,
  valueColor,
  rule,
  sub = null,
}: DashedCellProps): ReactElement {
  return (
    <div className="px-6 py-4" style={{ border: `2px dashed ${rule}` }}>
      <div className="cap" style={{ color: capColor }}>
        {cap}
      </div>
      <div className="mt-3 text-2xl font-extrabold" style={{ color: valueColor }}>
        {value}
      </div>
      {sub && (
        <div className="mt-2 text-sm" style={{ color: capColor }}>
          {sub}
        </div>
      )}
    </div>
  )
}
