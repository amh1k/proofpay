/**
 * Timestamps, for the thin top strip and the record block.
 *
 * The API sends ISO-8601 with an offset. Pakistan is Asia/Karachi, UTC+05:00, no
 * DST — but the browser is the merchant's own phone, so we render in local time
 * and never re-do the arithmetic ourselves.
 */

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** `"2026-08-20T15:44:00+05:00"` -> `"20 Aug 2026, 15:44"`. Null -> `null`. */
export function formatStamp(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** `"2026-08-20T15:44:00+05:00"` -> `"15:44"`. Null -> `null`. */
export function formatClock(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}
