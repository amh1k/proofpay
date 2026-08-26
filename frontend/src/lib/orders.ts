/**
 * What the merchant calls an order.
 *
 * A verification carries the ENGINE's order id — `order_demo_1002` — and the name
 * the merchant actually knows, `ORD-S01`, lives on the order and is never copied
 * into the result. So every surface that names an order has to translate, and
 * every surface that forgets to leaks a database key onto a shop counter.
 *
 * That happened: the history rows shipped reading `ORDER_DEMO_1001` in small caps
 * beside a verdict, on the same screen whose top strip had already translated the
 * same id correctly. One function, used by both, is the fix.
 *
 * The fallback is the raw id, not a blank and not an em dash. An order the list
 * does not have is rare — it means the row outlived its order, or the list failed
 * to load — and in that case an ugly true string beats a tidy silence: the
 * merchant can still read it back to someone.
 */

import type { Order } from '../types'

export function orderRef(orders: Order[] | null, orderId: string | null): string | null {
  if (orderId === null) return null
  const found = orders?.find((order) => order.id === orderId)
  return found?.external_order_ref ?? orderId
}
