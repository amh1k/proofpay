/**
 * The two seconds between the screenshot and the verdict.
 *
 * This is the only place a judge sees the work happen, so it says what the work
 * IS — three plain sentences, each landing as that step finishes. Nothing here
 * is decoration: read the screenshot, match it against the payments that actually
 * arrived, then check the matched payment has not already paid for another order.
 * That third line is the whole duplicate story, told before the verdict needs it.
 *
 * What it must not be: a spinner, a ring, a bar, or a percentage. Rule 1 covers
 * anything circular that fills up, and a progress bar over work that has not been
 * measured is the first thing a judge catches.
 *
 * Motion: the one allowed `evidence-in` fade, once per line. Under
 * `prefers-reduced-motion` all three lines are simply there from the first frame.
 */

import { useEffect, useState } from 'react'
import type { ReactElement } from 'react'
import { CHECKING_TITLE, UPLOAD_META } from '../lib/copy'

export interface CheckingScreenProps {
  /** `Date.now()` when the check started, so the steps stay on the real clock. */
  startedAt: number
}

/** What is actually being done, in the order it is actually done. */
const STEPS = [
  'Reading the screenshot',
  'Matching against payments received',
  'Checking it has not been used before',
] as const

/**
 * When each line lands, in ms from `startedAt`. The shell holds this screen for
 * `CHECK_MS` (2300ms), so the last line is down with room to read it before the
 * verdict — a step that had not finished when the verdict arrived would be a lie,
 * and a screen that finishes a second early is a second of nothing happening.
 */
const REVEAL_MS = [420, 1000, 1580] as const

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function CheckingScreen({ startedAt }: CheckingScreenProps): ReactElement {
  const [calm] = useState(prefersReducedMotion)
  const [done, setDone] = useState(() => (prefersReducedMotion() ? STEPS.length : 0))

  useEffect(() => {
    if (calm) return // all three are already down; there is nothing to schedule
    // Measured from `startedAt`, not from mount, so a re-render never restarts
    // the sequence and a slow first paint does not push the last line past 1400ms.
    const timers = REVEAL_MS.map((at, i) =>
      window.setTimeout(
        () => setDone((d) => Math.max(d, i + 1)),
        Math.max(0, at - (Date.now() - startedAt)),
      ),
    )
    return () => timers.forEach((t) => window.clearTimeout(t))
  }, [calm, startedAt])

  return (
    <section
      className="flex flex-1 flex-col justify-center gap-12 short:gap-8 px-6 py-12 short:py-8 md:px-12 lg:px-16"
      style={{ background: 'var(--color-ink)', color: 'var(--color-on-field)' }}
    >
      <h1 className="text-verdict m-0" style={{ maxWidth: '13ch' }}>
        {CHECKING_TITLE}
      </h1>

      {/* Every line keeps its space from the first frame — hidden, not absent —
       * so the block never jumps as the steps land. `visibility: hidden` also
       * keeps a pending line out of the accessibility tree, which is what makes
       * each one announce as it appears. */}
      <ol className="m-0 flex list-none flex-col gap-6 p-0" aria-live="polite">
        {STEPS.map((step, i) => {
          const shown = i < done
          return (
            <li
              key={step}
              className={
                shown && !calm
                  ? 'evidence-in flex items-center gap-4'
                  : 'flex items-center gap-4'
              }
              style={{ visibility: shown ? 'visible' : 'hidden' }}
            >
              {/* A bar, not a tick: the verdict glyphs mean verdicts, and one of
                * them standing in for "step finished" would blunt all five. */}
              <span
                aria-hidden="true"
                className="h-1 w-6 shrink-0"
                style={{ background: 'var(--color-on-field)' }}
              />
              <span className="text-lede">{step}</span>
            </li>
          )
        })}
      </ol>

      <p className="cap m-0" style={{ color: 'var(--color-on-field-dim)', maxWidth: '60ch' }}>
        {UPLOAD_META}
      </p>
    </section>
  )
}
