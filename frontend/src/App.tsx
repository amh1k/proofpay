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
  approveVerification,
  getVerification,
  listOrders,
  listVerifications,
  resetDemo,
  submitClaim,
} from './api/client'
import { NavStrip } from './components/NavStrip'
import type { FilterKey, NavKey } from './lib/nav'
import { orderRef } from './lib/orders'
import { HistoryScreen } from './screens/HistoryScreen'
import { TopStrip } from './components/TopStrip'
import { presentation, severity } from './lib/status'
import { CheckingScreen } from './screens/CheckingScreen'
import { ResultScreen } from './screens/ResultScreen'
import { UploadScreen, type ClaimSource, type DemoClaim } from './screens/UploadScreen'
import type { Order, VerificationResult, VerificationSummary } from './types'

/**
 * The four screens.
 *
 *     upload --(screenshot)--> checking --(verdict)--> result
 *        ^                                               |
 *        +--------------(dismiss)------------------------+
 *        |
 *     history --(tap a row)--> checking --> result
 *
 * `history` is reached from the three counting cells of the nav strip and from
 * nowhere else. It replays a past check through the SAME `runCheck` the upload
 * screen uses, so a verdict opened from the list is the identical screen the
 * merchant saw when it was first decided — including the hold, so the room sees
 * one rhythm whichever way a verdict arrives.
 */
export type Screen = 'upload' | 'checking' | 'result' | 'history'

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
  /** Null until the request lands, so the nav strip shows dashes and not zeros. */
  const [history, setHistory] = useState<VerificationSummary[] | null>(null)

  /**
   * Which nav cell's list is open. Kept even while another screen shows, so the
   * strip can still mark that cell as current — a merchant who opens a list,
   * taps a row and reads the verdict has not stopped being in "do not approve".
   */
  const [filter, setFilter] = useState<FilterKey>('blocked')

  /**
   * The orders, and which one the merchant chose.
   *
   * This lives here rather than in `UploadScreen` for the same reason every other
   * cross-screen fact does: the upload screen is unmounted while a check runs and
   * again while its verdict is on the wall, and a choice that evaporates on the
   * way to the answer is not a choice the merchant can trust. `startOver` and
   * `onDismiss` both clear the choice, deliberately — see there.
   *
   * `orders` is `null` until the server has answered, and goes BACK to null if it
   * fails. Null means "we do not know yet"; `[]` is the server telling us this
   * merchant has nothing waiting. The picker says those two things differently,
   * and it must never announce an empty order book we have not been told about.
   *
   * `selectedOrderId` is `null` as a real state, not a missing default. There is
   * no order until the merchant names one, and `submitClaim` is not called
   * without it.
   */
  const [orders, setOrders] = useState<Order[] | null>(null)
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null)

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

  /**
   * Whether the verdict on screen was opened from the history list.
   *
   * A ref, not state: nothing renders from it, and making it state would rerender
   * the verdict screen the moment a check starts for no visible reason.
   */
  const cameFromHistoryRef = useRef(false)

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  /**
   * The orders — on mount, and again on every reset.
   *
   * The retry is not politeness. This is the one request the live path cannot do
   * without: with no list there is nothing to pick, so "Check this payment" can
   * never become available, and a single failed round trip on venue wifi would
   * otherwise disable the whole product until someone reloaded the browser —
   * which is exactly what a presenter mid-story will not think to do. `startOver`
   * is always on screen and bound to Escape, so the recovery is the tap they
   * already know.
   *
   * A failure puts `orders` back to null, never to `[]`. The difference is what
   * the picker is allowed to say about the merchant's book; see the state above.
   */
  const loadOrders = useCallback(() => {
    listOrders()
      .then((items) => {
        if (aliveRef.current) setOrders(items)
      })
      .catch((e: unknown) => {
        if (!aliveRef.current) return
        setOrders(null)
        setError(errorText(e))
      })
  }, [])

  /**
   * Every check this merchant has run.
   *
   * Feeds two surfaces that want different things from it: the demo rail on the
   * upload screen picks three by status, and the history screen lists them. It is
   * sorted worst-first here so both read the same order — `HistoryScreen` sorts
   * again within a severity, which is a refinement of this rather than a
   * disagreement with it.
   */
  const loadHistory = useCallback(() => {
    listVerifications()
      .then((items) => {
        if (!aliveRef.current) return
        setHistory([...items].sort((a, b) => severity(a.status) - severity(b.status)))
      })
      .catch((e: unknown) => {
        if (aliveRef.current) setError(errorText(e))
      })
  }, [])

  useEffect(() => {
    loadOrders()
    loadHistory()
  }, [loadOrders, loadHistory])

  const demos: DemoClaim[] = useMemo(
    () =>
      (history ?? []).map((v) => ({
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

  /**
   * The single dispatch point. A demo button replays a stored verification and
   * needs no order; a real screenshot is always checked AGAINST one.
   *
   * The chosen id is read once, here, and closed over — so a merchant who changes
   * their mind while a check is in the air changes the NEXT check, never the one
   * whose verdict is already on its way to the wall.
   */
  const onSubmit = useCallback(
    (source: ClaimSource) => {
      const orderId = selectedOrderId
      cameFromHistoryRef.current = false // this one came from the upload screen
      void runCheck(() => {
        if (source.kind === 'demo') return getVerification(source.verificationId)
        // Unreachable from the UI — the upload screen disables the control until
        // an order is chosen. Kept because the alternative, once, was to pick an
        // order on the merchant's behalf, and that is the defect being fixed.
        if (orderId === null) {
          return Promise.reject(new Error('Choose which order this payment is for first.'))
        }
        return submitClaim(source.file, orderId)
      })
    },
    [runCheck, selectedOrderId],
  )

  /**
   * The merchant approved. Two memories, and they are not the same memory.
   *
   * `usedTxnIds` is this session's: it greys out the approve button if the same
   * payment comes back, and it is local because the demo's ledger is local.
   *
   * `approveVerification` is the backend's, and it is called for EVERY approval,
   * including the ones with no transaction to spend. What it records is the
   * screenshot, not the payment, and a screenshot is spent by the act of
   * approving whether or not a transaction was named. Calling it after the
   * `txnId` guard would have made screenshot reuse silently unreachable for any
   * verdict that names no transaction.
   */
  const onUse = useCallback((v: VerificationResult) => {
    void approveVerification(v.id)
    const txnId = v.matched_txn_id
    if (!txnId) return
    setUsedTxnIds((prev) => new Set(prev).add(txnId))
  }, [])

  /**
   * Leave this verdict. The used-payment memory survives — that is its whole job.
   *
   * The chosen order does NOT survive, for the same reason it does not survive a
   * reset: every button on a verdict screen comes back here — "Do not approve",
   * "Approve anyway", "Not now" — so this, not the reset, is the path a presenter
   * actually returns on. Leaving the choice filled in means the next screenshot
   * pasted onto that screen is instantly checkable against the PREVIOUS story's
   * order, with focus already on "Check this payment" and one Enter between the
   * room and a confident verdict about the wrong money. Nothing would ask, and
   * nothing on screen would be wrong — which is precisely the defect this picker
   * was built to remove.
   */
  const onDismiss = useCallback(() => {
    runRef.current += 1
    setResult(null)
    setSelectedOrderId(null)
    // Back where they came from. A verdict opened from a list is a merchant
    // reading DOWN a list — dropping them on the upload screen loses their place
    // and makes the next row cost two taps and a re-filter. A verdict from a
    // fresh check has no list behind it, so that one still returns to upload.
    setScreen(cameFromHistoryRef.current ? 'history' : 'upload')
  }, [])

  /**
   * Start over: a clean upload screen, whatever was happening a moment ago.
   *
   * It also forgets which payments were marked used, because "clean" is what the
   * next run of the demo needs — otherwise the second telling of the VERIFIED
   * story opens on a spent button. `resetDemo()` clears the server's side of the
   * same state when there is a server; on mocks it does nothing and says nothing.
   *
   * The chosen order goes too. `POST /demo/reset` cannot clear it — it is only
   * ever in this browser — so if it survived, the next telling would open with an
   * order already picked, which is both a stale choice and the wrong first beat:
   * the story starts by asking which order this is for.
   *
   * And the orders themselves are fetched again. This is the only always-visible
   * control, so it is also the only place a demo that opened before the backend
   * was up can be rescued without a browser reload.
   */
  const startOver = useCallback(() => {
    runRef.current += 1
    cameFromHistoryRef.current = false
    setResult(null)
    setError(null)
    setUsedTxnIds(new Set())
    setSelectedOrderId(null)
    setScreen('upload')
    void resetDemo()
    loadOrders()
    loadHistory()
  }, [loadOrders, loadHistory])

  /** Escape is the same control as the button, for the presenter's laptop. */
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') startOver()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [startOver])

  /**
   * The nav strip. The action cell starts a check; the other three open the list
   * of what they are counting.
   *
   * Opening a list refreshes it first. The counts in the strip are refetched by
   * `startOver`, but the LIST behind them was loaded once on mount — so without
   * this, a merchant who checks three payments and then taps a cell sees a figure
   * of 4 above a list of 1. A count and its list disagreeing is worse than either
   * being stale.
   */
  const onNav = useCallback(
    (key: NavKey) => {
      if (key === 'check') {
        startOver()
        return
      }
      runRef.current += 1 // an in-flight check must not land on top of the list
      setFilter(key)
      setScreen('history')
      loadHistory()
    },
    [startOver, loadHistory],
  )

  /** Replay a past check. Same path as a fresh one, hold included. */
  const onOpenFromHistory = useCallback(
    (verificationId: string) => {
      cameFromHistoryRef.current = true
      void runCheck(() => getVerification(verificationId))
    },
    [runCheck],
  )

  const shown = screen === 'result' ? result : null

  /**
   * What the top strip calls the order behind the verdict.
   *
   * Read off the RESULT, never off the picker. The merchant can change their
   * choice while a verdict is on the wall, and the strip must keep naming the
   * order this answer is about — including a demo-rail replay, which was checked
   * against an order nobody picked just now.
   *
   * A verification carries the ENGINE's order id (`order_demo_1002`); the name the
   * merchant knows lives on the order and is never copied into the result. So the
   * id is translated back through the list already loaded, falling back to the raw
   * id only for an order that is not one of ours — honest, and rare.
   *
   * Nothing is shown on the upload screen. The picker is right there saying which
   * order is chosen, in far larger type; repeating it in the chrome would be the
   * same fact twice on one screen.
   */
  const shownReference = shown === null ? null : orderRef(orders, shown.order_id)

  return (
    <div className="flex min-h-full flex-col">
      <TopStrip
        reference={shownReference}
        checkedAt={shown?.evaluated_at ?? null}
        provider={shown?.matched_transaction?.provider ?? shown?.claim.provider ?? null}
        onReset={startOver}
      />

      {screen === 'upload' && (
        <UploadScreen
          onSubmit={onSubmit}
          orders={orders}
          selectedOrderId={selectedOrderId}
          onSelectOrder={setSelectedOrderId}
          demos={demos}
          error={error}
        />
      )}
      {screen === 'history' && (
        <HistoryScreen
          filter={filter}
          items={history ?? []}
          orders={orders}
          onOpen={onOpenFromHistory}
          error={error}
        />
      )}
      {screen === 'checking' && <CheckingScreen startedAt={startedAt} />}
      {screen === 'result' && result && (
        <ResultScreen
          result={result}
          used={result.matched_txn_id !== null && usedTxnIds.has(result.matched_txn_id)}
          onUse={onUse}
          onDismiss={onDismiss}
        />
      )}

      {/* The strip marks where the merchant is: the action cell on the upload
        * screen, the open list's cell on the list. A verdict marks neither —
        * a verdict is not a place in the app, it is an answer. */}
      <NavStrip
        items={history}
        active={screen === 'upload' ? 'check' : screen === 'history' ? filter : null}
        onSelect={onNav}
      />
    </div>
  )
}
