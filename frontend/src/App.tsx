/**
 * PLACEHOLDER — delete this and build the real UI.
 *
 * This exists only to prove the wiring works: Tailwind is applied, the mock layer
 * loads, and the data shape is the one the live API returns. It is deliberately
 * unstyled and deliberately not a design.
 *
 * The screen that matters is the RESULT VIEW. See issue #4.
 */

import { useEffect, useState } from 'react'
import { listVerifications, usingMocks } from './api/client'
import { formatMoney, type VerificationResult } from './types'

const MARK: Record<string, string> = {
  AGREE: '✓',
  WEAK: '⚠',
  CONTRADICT: '✗',
  MISSING: '?',
}

export default function App() {
  const [items, setItems] = useState<VerificationResult[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listVerifications()
      .then((data) => setItems(data.items))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  return (
    <main className="mx-auto max-w-3xl p-8 font-sans">
      <h1 className="text-2xl font-bold">ProofPay — scaffold</h1>
      <p className="mt-1 text-sm text-gray-600">
        Wiring check only. Replace <code>src/App.tsx</code> with the real UI.
        {usingMocks && ' Running on mock data generated from the real engine.'}
      </p>

      {loading && <p className="mt-8">Loading…</p>}
      {error && <p className="mt-8 text-red-600">{error}</p>}

      <div className="mt-8 space-y-6">
        {items.map((v) => (
          <section key={v.id} className="rounded border border-gray-300 p-4">
            <div className="flex items-baseline justify-between">
              <span className="font-semibold">{v.status}</span>
              <span className="text-xs text-gray-500">
                risk {v.risk} · rule {v.fired_rule_id}
              </span>
            </div>

            <p className="mt-1 text-sm">{v.summary}</p>

            <table className="mt-3 w-full text-sm">
              <tbody>
                {v.evidence.map((e) => (
                  <tr key={e.field} className="border-t border-gray-200">
                    <td className="w-6 py-1">{MARK[e.agreement]}</td>
                    <td className="py-1 pr-4 text-gray-600">{e.field}</td>
                    <td className="py-1 pr-4">{e.claimed_value ?? '—'}</td>
                    <td className="py-1 pr-4 text-gray-500">{e.recorded_value ?? '—'}</td>
                    <td className="py-1 text-gray-500">{e.label}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <p className="mt-3 text-sm font-medium">{v.recommended_action}</p>
            <p className="mt-1 text-xs text-gray-400">
              order {v.order_id} · claimed {formatMoney(v.claim.amount_minor)} · matched{' '}
              {v.matched_txn_id ?? 'none'}
            </p>
          </section>
        ))}
      </div>
    </main>
  )
}
