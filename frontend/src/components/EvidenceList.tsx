/**
 * The per-field evidence, below the sign.
 *
 * The sign says the verdict; this says why, field by field. It sits under the
 * verdict inside the same field, so it clears the fold on a projector and is one
 * scroll away for the merchant who wants it.
 *
 * Two things it will not do:
 *
 *  - it never reads `score`. The mark comes from `agreement`, because a very
 *    common name agrees WEAKLY without contradicting anything, and a cross there
 *    tells the merchant the opposite of the truth.
 *  - with `collapse`, it folds every AGREE row into ONE line — but it never drops
 *    them. On a mismatch those agreements are the proof the transaction is REAL,
 *    which is the whole difference between "the amount was edited" and "your
 *    customer is a fraud".
 *
 * A row with no value renders italic `NOT_SHOWN` (rule 8), never a blank. The
 * only motion is the one-shot `evidence-in` fade, staggered across the first few
 * rows and then finished. Rule 10.
 *
 * Added for the verdict screens; not a foundation file.
 */

import type { ReactElement } from 'react'
import { AgreementMark } from './AgreementMark'
import { NOT_SHOWN } from '../lib/copy'
import { agreedSummary, rowMatchCount, type EvidenceRow } from '../lib/evidence'
import type { StatusPresentation } from '../lib/status'

export interface EvidenceListProps {
  rows: readonly EvidenceRow[]
  /** From `presentation(result.status)`. Every colour comes from here. */
  look: StatusPresentation
  /** The caption above the block, e.g. "What we checked". */
  title: string
  /**
   * False on a list that is not a comparison — the receipt's own fields on a
   * NOT FOUND verdict, where a tick or a cross would imply a judgement we did
   * not make. Default true.
   */
  marks?: boolean
  /**
   * Fold the AGREE rows into a single line. Default false, so a screen that
   * wants every row listed gets every row.
   */
  collapse?: boolean
  /**
   * What to say where the merchant's record has no value. NOT the same as a
   * blank on the screenshot side: this one means there is no transaction to read
   * it from, either because none arrived or because the engine refused to choose.
   */
  recordedFallback?: string
}

/** 240ms each, 40ms apart, and then it stops. */
function delay(index: number): string {
  return `${Math.min(index, 3) * 40}ms`
}

interface ValueCellProps {
  cap: string
  value: string | null
  fallback: string
  numeric: boolean
  look: StatusPresentation
}

function ValueCell({ cap, value, fallback, numeric, look }: ValueCellProps): ReactElement {
  return (
    <div style={{ flex: '1 1 150px' }}>
      <div className="cap" style={{ color: look.support }}>
        {cap}
      </div>
      <div
        className={numeric && value !== null ? 'num mt-2 text-lg' : 'mt-2 text-lg'}
        style={value === null ? { color: look.support, fontStyle: 'italic' } : undefined}
      >
        {value ?? fallback}
      </div>
    </div>
  )
}

export function EvidenceList({
  rows,
  look,
  title,
  marks = true,
  collapse = false,
  recordedFallback = 'not in this transaction',
}: EvidenceListProps): ReactElement | null {
  if (rows.length === 0) return null

  const agreed = collapse ? rows.filter((r) => r.agreement === 'AGREE') : []
  const listed = collapse ? rows.filter((r) => r.agreement !== 'AGREE') : rows

  const twoSided = rows.some((r) => r.agreement !== null)
  const seam = look.polarity === 'hollow' ? look.rule : look.support
  const hairline = `2px ${look.dashed ? 'dashed' : 'solid'} ${seam}`

  const summary = collapse ? agreedSummary(rows) : null
  const count = twoSided ? rowMatchCount(rows) : null

  return (
    <div className="pt-6" style={{ borderTop: hairline }}>
      <div className="flex flex-wrap items-baseline gap-4">
        <h2 className="cap m-0 font-normal" style={{ color: look.support }}>
          {title}
        </h2>
        {count && (
          <>
            <span className="flex-1" />
            <span className="num text-sm" style={{ color: look.support }}>
              {count}
            </span>
          </>
        )}
      </div>

      <ul className="m-0 mt-3 list-none p-0">
        {listed.map((row, i) => (
          <li
            key={row.key}
            className="evidence-in flex flex-wrap items-start gap-4 py-4"
            style={{ borderTop: hairline, animationDelay: delay(i) }}
          >
            {marks && row.agreement !== null && <AgreementMark agreement={row.agreement} />}

            <div style={{ flex: '1 1 180px' }}>
              <div className="text-lg font-bold">{row.label}</div>
              {row.detail && (
                <div className="text-sm" style={{ color: look.support }}>
                  {row.detail}
                </div>
              )}
            </div>

            {twoSided ? (
              <div className="flex flex-wrap gap-6" style={{ flex: '2 1 260px' }}>
                <ValueCell
                  cap="On the screenshot"
                  value={row.claimed}
                  fallback={NOT_SHOWN}
                  numeric={row.numeric}
                  look={look}
                />
                <ValueCell
                  cap="In your account"
                  value={row.recorded}
                  fallback={recordedFallback}
                  numeric={row.numeric}
                  look={look}
                />
              </div>
            ) : (
              <div
                className={row.numeric && row.claimed !== null ? 'num text-lg' : 'text-lg'}
                style={
                  row.claimed === null
                    ? { flex: '1 1 160px', color: look.support, fontStyle: 'italic' }
                    : { flex: '1 1 160px' }
                }
              >
                {row.claimed ?? NOT_SHOWN}
              </div>
            )}
          </li>
        ))}

        {summary && (
          <li
            className="evidence-in flex flex-wrap items-center gap-3 py-4"
            style={{ borderTop: hairline, animationDelay: delay(listed.length) }}
          >
            {agreed.map((row, i) => (
              <span key={row.key} className="flex items-center gap-2">
                {i > 0 && (
                  <span aria-hidden="true" style={{ color: look.support }}>
                    ·
                  </span>
                )}
                <AgreementMark agreement="AGREE" size={16} labelled={false} />
                <span className="text-lg">{row.label}</span>
              </span>
            ))}
            <span className="text-lg" style={{ color: look.support }}>
              — {summary}
            </span>
          </li>
        )}
      </ul>
    </div>
  )
}
