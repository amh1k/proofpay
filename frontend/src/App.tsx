/**
 * The shell. Three screens, one strip above, one strip below.
 *
 *     upload  --(screenshot)-->  checking  --(verdict)-->  result
 *        ^                                                    |
 *        +------------------(dismiss)-------------------------+
 *        ^                                                    |
 *        +--------------(Start over / Esc)--------------------+
 *
 * This file owns state and transitions ONLY. Every pixel of the three screens
 * belongs to `src/screens/*`; every colour and word belongs to `src/lib/status.ts`
 * and `src/lib/copy.ts`. If you are about to write a hex code here, you are in the
 * wrong file.
 *
 * Two things here exist because this is demonstrated live, four or five runs back
 * to back, on someone else's projector:
 *
 *   THE HOLD    A check is not shown the instant it resolves. The checking screen
 *               holds for `CHECK_MS` while the API call runs beside it, so the
 *               verdict lands at the same moment every time — on mocks, on a live
 *               backend, and on venue wifi. The room sees a rhythm, not a race.
 *   THE RESET   One control, always on screen, plus Escape. It cancels whatever
 *               is in flight, clears the used-payment memory and returns a clean
 *               upload screen. A demo that cannot be restarted in one tap is a
 *               demo that gets restarted by reloading the page in front of judges.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactElement } from 'react'
import {
  getDashboard,
  getVerification,
  listVerifications,
  resetDemo,
  submitClaim,
} from './api/client'
import { NavStrip } from './components/NavStrip'
import type { NavKey } from './lib/nav'
import { TopStrip } from './components/TopStrip'
import { presentation, severity } from './lib/status'
import { CheckingScreen } from './screens/CheckingScreen'
import { ResultScreen } from './screens/ResultScreen'
import { UploadScreen, type ClaimSource, type DemoClaim } from './screens/UploadScreen'
import type { DashboardSummary, VerificationResult, VerificationSummary } from './types'

/** The three screens. There is no fourth; a list view is a later stage. */
export type Screen = 'upload' | 'checking' | 'result'

/**
 * How long the checking screen holds before the verdict lands.
 *
 * The three lines on that screen finish at 1600ms (`CheckingScreen.REVEAL_MS`),
 * so the last one is down and readable before this expires. Under two seconds
 * feels like a lookup; much over three and the room starts to wonder.
 */
const CHECK_MS = 2300

const hold = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

function errorText(reason: unknown): string {
  if (reason instanceof Error && reason.message.trim() !== '') return reason.message
  return 'That check could not be completed. Try again.'
}

export default function App(): ReactElement {
  const [screen, setScreen] = useState<Screen>('upload')
  const [result, setResult] = useState<VerificationResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [startedAt, setStartedAt] = useState<number>(() => Date.now())
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [history, setHistory] = useState<VerificationSummary[]>([])

  /**
   * Which transactions have been spent. This is the whole point of "Use it": the
   * same genuine receipt sent twice must come back DUPLICATE the second time.
   * In-memory for now — persisting it belongs with the API-integration stage.
   */
  const [usedTxnIds, setUsedTxnIds] = useState<ReadonlySet<string>>(() => new Set())

  /**
   * Which check is current. Bumped by every new check AND by the reset, so a
   * verdict that resolves after the merchant has moved on is dropped instead of
   * appearing over whatever they are looking at now.
   */
  const runRef = useRef(0)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  const loadSummary = useCallback(() => {
    getDashboard()
      .then((d) => {
        if (aliveRef.current) setSummary(d)
      })
      .catch(() => undefined) // the strip shows em dashes; it is not worth an alert
  }, [])

  useEffect(() => {
    loadSummary()
    listVerifications()
      .then((items) => {
        if (!aliveRef.current) return
        setHistory([...items].sort((a, b) => severity(a.status) - severity(b.status)))
      })
      .catch((e: unknown) => {
        if (aliveRef.current) setError(errorText(e))
      })
  }, [loadSummary])

  const demos: DemoClaim[] = useMemo(
    () =>
      history.map((v) => ({
        id: v.id,
        label: presentation(v.status).short,
        status: v.status,
      })),
    [history],
  )

  /**
   * One check, whatever the source. The API call and the hold run together, so
   * the screen time is `max(CHECK_MS, however long the API took)` — never their
   * sum, and never a flicker when a mock resolves in 250ms.
   */
  const runCheck = useCallback(async (load: () => Promise<VerificationResult>) => {
    const run = runRef.current + 1
    runRef.current = run

    setError(null)
    setResult(null)
    setStartedAt(Date.now())
    setScreen('checking')

    const [settled] = await Promise.allSettled([load(), hold(CHECK_MS)])

    // A reset, or a newer check, happened while this one was in the air.
    if (!aliveRef.current || runRef.current !== run) return

    if (settled.status === 'fulfilled') {
      setResult(settled.value)
      setScreen('result')
    } else {
      setError(errorText(settled.reason))
      setScreen('upload')
    }
  }, [])

  const onSubmit = useCallback(
    (source: ClaimSource) => {
      void runCheck(() =>
        source.kind === 'demo'
          ? getVerification(source.verificationId)
          : submitClaim(source.file),
      )
    },
    [runCheck],
  )

  const onUse = useCallback((v: VerificationResult) => {
    const txnId = v.matched_txn_id
    if (!txnId) return
    setUsedTxnIds((prev) => new Set(prev).add(txnId))
  }, [])

  /** Leave this verdict. The used-payment memory survives — that is its whole job. */
  const onDismiss = useCallback(() => {
    runRef.current += 1
    setResult(null)
    setScreen('upload')
  }, [])

  /**
   * Start over: a clean upload screen, whatever was happening a moment ago.
   *
   * It also forgets which payments were marked used, because "clean" is what the
   * next run of the demo needs — otherwise the second telling of the VERIFIED
   * story opens on a spent button. `resetDemo()` clears the server's side of the
   * same state when there is a server; on mocks it does nothing and says nothing.
   */
  const startOver = useCallback(() => {
    runRef.current += 1
    setResult(null)
    setError(null)
    setUsedTxnIds(new Set())
    setScreen('upload')
    void resetDemo()
    loadSummary()
  }, [loadSummary])

  /** Escape is the same control as the button, for the presenter's laptop. */
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') startOver()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [startOver])

  const onNav = useCallback(
    (key: NavKey) => {
      // Only the action cell does anything today. The three count cells become
      // filtered lists in a later stage; they are deliberately inert, not fake.
      if (key === 'check') startOver()
    },
    [startOver],
  )

  const shown = screen === 'result' ? result : null

  return (
    <div className="flex min-h-full flex-col">
      <TopStrip
        reference={shown?.order_id ?? null}
        checkedAt={shown?.evaluated_at ?? null}
        provider={shown?.matched_transaction?.provider ?? shown?.claim.provider ?? null}
        onReset={startOver}
      />

      {screen === 'upload' && <UploadScreen onSubmit={onSubmit} demos={demos} error={error} />}
      {screen === 'checking' && <CheckingScreen startedAt={startedAt} />}
      {screen === 'result' && result && (
        <ResultScreen
          result={result}
          used={result.matched_txn_id !== null && usedTxnIds.has(result.matched_txn_id)}
          onUse={onUse}
          onDismiss={onDismiss}
        />
      )}

      <NavStrip summary={summary} active={screen === 'upload' ? 'check' : null} onSelect={onNav} />
    </div>
  )
}
