/**
 * The entry point.
 *
 * The merchant arrives here holding a screenshot the customer sent on WhatsApp.
 *
 * TWO THINGS HAPPEN ON THIS SCREEN, AND THE ORDER OF THEM IS THE DESIGN:
 *
 *     which order is this for?          the picker, at the top
 *              |
 *              v
 *     here is the proof                 the dashed target, below it
 *              |
 *              v
 *     check this payment                the action, below both
 *
 * The picker is first because a screenshot on its own decides nothing. "Is this
 * payment real" is always "is this payment real FOR THIS ORDER" — the expected
 * amount lives on the order, and so does whether the transaction on the receipt
 * has already been spent. Put the picker underneath the target and the merchant
 * reaches the button having answered only half the question; the app then has to
 * choose an order for them, which is precisely the bug this screen was built to
 * remove.
 *
 * Three ways to hand over the proof, and they are not equal:
 *
 *   PASTE   the primary one. A merchant on a laptop copies the image out of
 *           WhatsApp Web and hits Ctrl+V. The listener is on `window`, so it
 *           works without focusing anything first.
 *   DROP    the same gesture with a mouse.
 *   PICK    a visible button, for a phone and for keyboard users.
 *
 * And then the demo rail, which is not a convenience: a projector demo dies on a
 * file picker or on venue wifi, so the three interesting verdicts must be one tap
 * away with nothing between them and the screen.
 *
 * Signage register throughout: one very large line, one dashed field, generous
 * clear space, no chrome. Every button is transparent with a 3px border and they
 * are all the same weight — nothing here decides for the merchant.
 */

import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { CSSProperties, DragEvent, KeyboardEvent, ReactElement } from 'react'
import {
  ORDER_NONE,
  ORDER_PICKER_HINT,
  ORDER_REQUIRED,
  UPLOAD_HINT,
  UPLOAD_META,
  UPLOAD_TITLE,
} from '../lib/copy'
import { formatMoney } from '../lib/money'
import { presentation } from '../lib/status'
import type { Order, VerificationStatus } from '../types'

/** What the merchant handed us. A file is the real path; a demo replays a fixture. */
export type ClaimSource =
  | { kind: 'file'; file: File }
  | { kind: 'paste'; file: File }
  | { kind: 'demo'; verificationId: string }

/** One button on the demo rail. */
export interface DemoClaim {
  /** Verification id to replay, e.g. `"ver_suspicious"`. */
  id: string
  /** Two or three words, from `presentation(status).short`. */
  label: string
  status: VerificationStatus
}

export interface UploadScreenProps {
  /** Hand a screenshot to the app. The shell moves to `checking` and calls the API. */
  onSubmit: (source: ClaimSource) => void
  /**
   * The orders waiting for a payment, in the server's own order. Never re-sorted
   * here: the backend picks that sequence deliberately, and buttons that move
   * between runs slide out from under the presenter's finger.
   *
   * `null` means we have not been told yet — the request is in flight, or it
   * failed. `[]` means the server told us there are none. The caption above the
   * picker says those two things differently, because only one of them is a
   * statement about the merchant's book.
   */
  orders: Order[] | null
  /** Which one the merchant has chosen. Null until they choose; there is no default. */
  selectedOrderId: string | null
  onSelectOrder: (orderId: string) => void
  /** Demo buttons, in worst-first order. Empty until the fixtures load. */
  demos: DemoClaim[]
  /** Set when the previous check failed. Render it; do not swallow it. */
  error: string | null
}

/* ── words that belong to this screen ───────────────────────────────────────
 * `copy.ts` is a foundation file, so the lines that exist only here live here.
 * If they outlive this stage, move them there — do not duplicate them. */

/** The line under the title. "the payment proof THEY sent you" — whose it is matters. */
const DROP_SUB = 'the payment proof they sent you — or paste it, or take a photo'

const PASTE_HINT = 'or press Ctrl + V to paste'

/** The register of rule 8, applied to a wrong file: say what we can use, not what they did. */
const NOT_AN_IMAGE = 'That is not an image. Share the screenshot itself.'

/* ── the ink ground ─────────────────────────────────────────────────────────
 * Alphas of white, like the hairlines in `TopStrip`. No new hue enters here. */
const DASH = 'rgba(255,255,255,.32)'
const DASH_LIVE = 'rgba(255,255,255,.72)'
const WASH = 'rgba(255,255,255,.06)'

/** Every button on this screen. Rule 5: one weight, no primary. */
const BUTTON: CSSProperties = {
  background: 'transparent',
  border: '3px solid var(--color-on-field)',
  color: 'var(--color-on-field)',
}

const BUTTON_CLASS = 'flex cursor-pointer items-center gap-3 px-8 py-4 text-lg font-bold'

/**
 * The chosen order, and only the chosen order.
 *
 * Rule 5 — one weight, no primary — is about ACTIONS: two buttons that answer the
 * merchant's question must never be drawn so that the product has answered it for
 * them. A selection is not an answer to anything; it is a readback of what the
 * merchant already did, and a readback nobody can see from the back of a room is
 * not a readback at all.
 *
 * So the chosen order inverts: the same 3px rectangle, filled. Every other button
 * on this screen stays an outline, which makes exactly one filled sign on the
 * page and no possible confusion about what it means. No new hue enters — the
 * white that was the ink becomes the ground, and the label takes the ink token
 * for a white ground, nothing more, so it holds up in grayscale and on a
 * washed-out projector alike.
 *
 * `--color-on-paper`, not `--color-ink`. They are the same value today, and that
 * is exactly the trap: `--color-ink` is annotated in `theme.css` as the GROUND
 * for chrome, and `--color-on-paper` / `--color-on-paper-dim` is the pair that
 * means ink on a white field — the pair `status.ts` binds for every hollow
 * verdict, and the pair the figure inside this very button already uses. Inking
 * the two halves of one label from two token families is how a later edit to the
 * chrome ground silently drags one of them along.
 */
const BUTTON_CHOSEN: CSSProperties = {
  background: 'var(--color-on-field)',
  border: '3px solid var(--color-on-field)',
  color: 'var(--color-on-paper)',
}

/**
 * An order button: the reference, then the figure it is waiting for.
 *
 * Always stacked, never side by side. Two short strings on one line read as a
 * single run of characters at distance — and, measured, the wide single-line form
 * is what makes five of these stop fitting across a 1280px projector in
 * `?present=1`. They then wrap to two rows, which costs MORE height than stacking
 * them did. `short:` only takes the padding down.
 *
 * This block is new above the fold, and every pixel it costs comes off the
 * distance between "Check this payment" and the bottom of a 720p screen. Measure
 * before changing it; do not reason about it.
 */
const PICKER_CLASS =
  'flex cursor-pointer flex-col items-start gap-1 px-8 py-4 text-lg font-bold' +
  ' short:px-6 short:py-2'

/**
 * The demo rail, in the order a demo is told: the edited amount first, because it
 * is the one nobody believes until they see it, then the already-used receipt,
 * then the payment that has simply not landed yet.
 *
 * Named RAIL_ORDER, not DEMO_ORDER: since the picker landed, "order" in this file
 * means a merchant's order — the thing with a reference and an expected amount —
 * and a constant called DEMO_ORDER sitting next to `orders` would read as the
 * demo's order rather than as the rail's sequence. This one is a sort order.
 *
 * The labels come from `presentation(status).short`, never from a string here —
 * the words for a status live in exactly one table.
 */
const RAIL_ORDER: readonly VerificationStatus[] = ['SUSPICIOUS', 'DUPLICATE', 'UNMATCHED']

function demoRail(demos: DemoClaim[]): DemoClaim[] {
  const picked: DemoClaim[] = []
  for (const status of RAIL_ORDER) {
    const found = demos.find((d) => d.status === status)
    if (found) picked.push(found)
  }
  // If the fixture set ever changes shape, show something rather than nothing.
  return picked.length > 0 ? picked : demos.slice(0, 3)
}

/**
 * How an order came to be chosen, and the distinction is not pointer-vs-keyboard.
 *
 *   PRESS   the merchant activated that button — a click, or Space/Enter on it.
 *           They are done: this is the order.
 *   ARROW   the selection moved under the arrow keys. Standard radio behaviour
 *           selects as it moves, so this is a choice IN PROGRESS — the next key
 *           may well move it again, and until then the focus belongs to the
 *           group and nothing else on the screen may take it. See the
 *           ready-effect below, which is what used to take it.
 */
type SelectionSource = 'press' | 'arrow'

interface OrderPickerProps {
  orders: Order[] | null
  selectedOrderId: string | null
  onSelect: (orderId: string, from: SelectionSource) => void
}

/**
 * Which order this payment is for.
 *
 * A single-choice control, so it is a real radiogroup and not a row of buttons
 * that merely look chosen. That matters twice over:
 *
 *   - The fill is the visual carrier, but `aria-checked` is the one a screen
 *     reader reads. Neither is allowed to be the only one.
 *   - Radios are a ROVING TABINDEX: one stop in the tab order for the whole
 *     group, arrows to move within it. Five separate tab stops between the
 *     merchant and the drop target would make the keyboard path worse than the
 *     mouse one, which is the opposite of what this is for.
 *
 * Arrowing moves the selection with the focus, which is the standard behaviour
 * for radios and is safe here because selecting an order commits to nothing —
 * the check only runs when "Check this payment" is pressed.
 *
 * Nothing is preselected, even when only one order comes back. An order that the
 * app chose is exactly what the merchant then fails to notice, and this screen
 * exists because that happened.
 */
function OrderPicker({ orders, selectedOrderId, onSelect }: OrderPickerProps): ReactElement {
  const captionId = useId()
  const groupRef = useRef<HTMLDivElement>(null)

  /** Not yet known and known to be empty render the same row of nothing. */
  const rows = orders ?? []

  /** Move selection AND focus by `delta`, wrapping. `from` is the current index. */
  const move = (from: number, delta: number) => {
    const count = rows.length
    if (count === 0) return
    const index = (((from + delta) % count) + count) % count
    const next = rows[index]
    if (!next) return
    onSelect(next.id, 'arrow')
    // The buttons are already in the DOM, so focus can move before React
    // re-renders; querying the group keeps this from needing a ref per row.
    const radios = groupRef.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]')
    radios?.[index]?.focus()
  }

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        e.preventDefault()
        move(index, 1)
        break
      case 'ArrowLeft':
      case 'ArrowUp':
        e.preventDefault()
        move(index, -1)
        break
      case 'Home':
        e.preventDefault()
        move(0, 0)
        break
      case 'End':
        e.preventDefault()
        move(rows.length - 1, 0)
        break
      default:
        break // Space and Enter are the button's own job
    }
  }

  return (
    <div className="flex flex-col gap-4 short:gap-2">
      {/* Three states, two lines. ORDER_NONE is an assertion about the
        * merchant's book — "no orders are waiting for a payment right now" — so
        * it is said ONLY when the server has actually said it. While the list is
        * in flight, or after it failed, the caption stays the question it will
        * still be asking once the buttons land: a question claims nothing, and
        * the words do not change under the room when they arrive. The failure
        * itself is not swallowed — it is on screen, in red, further down. */}
      <p id={captionId} className="cap m-0" style={{ color: 'var(--color-on-field-dim)' }}>
        {orders !== null && orders.length === 0 ? ORDER_NONE : ORDER_PICKER_HINT}
      </p>

      <div
        ref={groupRef}
        role="radiogroup"
        aria-labelledby={captionId}
        className="flex flex-wrap gap-4 short:gap-2"
      >
        {rows.map((order, index) => {
          const chosen = order.id === selectedOrderId
          // Exactly one tab stop. Before anything is chosen that is the first
          // row, so tabbing into the group always lands somewhere.
          const tabbable = chosen || (selectedOrderId === null && index === 0)
          return (
            <button
              key={order.id}
              type="button"
              role="radio"
              aria-checked={chosen}
              tabIndex={tabbable ? 0 : -1}
              onClick={() => onSelect(order.id, 'press')}
              onKeyDown={(e) => onKeyDown(e, index)}
              className={PICKER_CLASS}
              style={chosen ? BUTTON_CHOSEN : BUTTON}
            >
              <span className="num">{order.external_order_ref}</span>
              {/* Rule 7: paisa through `formatMoney`, never a rupee string built
                * here. `num` and NOT `cap`, even though this is a small dim line
                * and `cap` is what the rest of the screen uses for those: `cap`
                * uppercases, and it turns "Rs 1,500" into "RS 1,500". The unit on
                * a figure is not a caption. */}
              <span
                className="num text-base"
                style={{
                  color: chosen ? 'var(--color-on-paper-dim)' : 'var(--color-on-field-dim)',
                }}
              >
                {formatMoney(order.expected_amount_minor, order.currency)}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

/** First image in a drop / paste / pick. A WhatsApp share can carry more than one. */
function pickImage(files: FileList | null): File | null {
  if (!files) return null
  for (let i = 0; i < files.length; i += 1) {
    const f = files.item(i)
    if (f && f.type.startsWith('image/')) return f
  }
  return null
}

/** The screenshot in hand: the file, how it arrived, and its preview URL. */
interface Claim {
  file: File
  url: string
  kind: 'file' | 'paste'
}

export function UploadScreen({
  onSubmit,
  orders,
  selectedOrderId,
  onSelectOrder,
  demos,
  error,
}: UploadScreenProps): ReactElement {
  const inputRef = useRef<HTMLInputElement>(null)
  const submitRef = useRef<HTMLButtonElement>(null)
  /** So the disabled action can point a screen reader at the reason it is disabled. */
  const hintId = useId()
  /** The live object URL, so exactly one exists and it is always revoked. */
  const urlRef = useRef<string | null>(null)

  const [claim, setClaim] = useState<Claim | null>(null)
  const [dragging, setDragging] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  /**
   * True while the merchant's most recent action was an ARROW move in the picker,
   * and only until anything else happens. A ref rather than state: it changes
   * what an effect does in the same commit, and must not cause a render itself.
   */
  const arrowedRef = useRef(false)

  /** Every route into the picker's `onSelect`, remembering how it was chosen. */
  const chooseOrder = useCallback(
    (orderId: string, from: SelectionSource) => {
      arrowedRef.current = from === 'arrow'
      onSelectOrder(orderId)
    },
    [onSelectOrder],
  )

  const release = useCallback(() => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    urlRef.current = null
  }, [])

  // The only effect touching the URL is the one that cleans it up on the way out.
  useEffect(() => release, [release])

  const take = useCallback(
    (next: File | null, how: 'file' | 'paste') => {
      if (!next) {
        setNotice(NOT_AN_IMAGE)
        return
      }
      release()
      const url = URL.createObjectURL(next)
      urlRef.current = url
      setNotice(null)
      // The screenshot is now the last thing that happened, so the merchant is
      // no longer mid-choice in the picker: the check may take the focus.
      arrowedRef.current = false
      setClaim({ file: next, url, kind: how })
    },
    [release],
  )

  const clear = useCallback(() => {
    release()
    setClaim(null)
    setNotice(null)
  }, [release])

  /** Ctrl+V anywhere on the screen. This is the interaction merchants actually use. */
  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      const data = e.clipboardData
      if (!data || data.files.length === 0) return // pasted text is not an attempt to share
      e.preventDefault()
      take(pickImage(data.files), 'paste')
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [take])

  /** A miss outside the target must not make the browser navigate to the image. */
  useEffect(() => {
    const stop = (e: Event) => e.preventDefault()
    window.addEventListener('dragover', stop)
    window.addEventListener('drop', stop)
    return () => {
      window.removeEventListener('dragover', stop)
      window.removeEventListener('drop', stop)
    }
  }, [])

  const pick = useCallback(() => inputRef.current?.click(), [])

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Enter' && e.key !== ' ') return
    e.preventDefault()
    pick()
  }

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(true)
  }

  const onDragLeave = (e: DragEvent<HTMLDivElement>) => {
    // Moving onto a child is not leaving. Without this the border flickers.
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return
    setDragging(false)
  }

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    take(pickImage(e.dataTransfer.files), 'file')
  }

  const submit = () => {
    if (!claim || !selectedOrderId) return
    const { file, kind } = claim
    onSubmit(kind === 'paste' ? { kind: 'paste', file } : { kind: 'file', file })
  }

  const rail = demoRail(demos)
  const message = notice ?? error

  /**
   * Both halves have to be in hand before a check can run. This is the only gate:
   * there is no "pick one for me" path, because inventing an order is the failure
   * this screen was rebuilt to prevent.
   */
  const ready = claim !== null && selectedOrderId !== null

  // One caption slot beside the actions. Once a screenshot is in hand the paste
  // hint has done its job, so the slot says the thing still standing in the way.
  const hint = claim && !selectedOrderId ? ORDER_REQUIRED : PASTE_HINT

  /**
   * Focus the check the moment both halves are in hand, whichever arrived last,
   * and put it where it can be seen.
   *
   * The focus replaces the old `autoFocus`, which fired when the button mounted —
   * i.e. only when the screenshot came second. A merchant who pastes first and
   * then picks the order would otherwise be left hunting for the button with the
   * mouse, and "paste, Enter" is the whole reason focus is moved at all.
   *
   * The scroll is the one that matters on a projector. This screen is taller than
   * a 720p viewport in `?present=1` — it was before the picker and it is more so
   * now — and `focus()` alone only scrolls the button to the nearest edge, which
   * lands it flush against the bottom of the screen. `block: 'center'` puts it in
   * the middle instead. Instant, not smooth: nothing on this screen animates.
   *
   * NEITHER HAPPENS WHILE THE MERCHANT IS ARROWING THROUGH THE PICKER.
   *
   * `ready` in the deps keeps this from firing on every later arrow press, but
   * the FIRST one is the press that makes `ready` true — so with a screenshot
   * already in hand, ArrowRight used to select order two and throw the focus onto
   * "Check this payment" in the same beat. The presenter, still arrowing towards
   * the order they meant, then pressed keys at a plain button and finally Enter,
   * and the room got a confident verdict about an order nobody chose. The scroll
   * made it worse: it can carry the picker — the only readback of what is
   * selected — off the top of a 720p projector.
   *
   * So an arrow move is left alone entirely. Their next Tab reaches the check,
   * and the caption beside it already says what is still missing.
   */
  useEffect(() => {
    if (!ready) return
    if (arrowedRef.current) return
    const button = submitRef.current
    button?.focus()
    button?.scrollIntoView({ block: 'center', behavior: 'auto' })
  }, [ready])

  return (
    <section
      /* `short:gap-4`, tightened from `gap-6` when the picker landed. The screen
       * gained a whole block above the drop target, and on a 720p projector the
       * rhythm is what pays for it — the alternative is shrinking type that has to
       * carry to the back of a room. Rule: `short:` may tighten spacing, never
       * type. */
      className="flex flex-1 flex-col gap-8 px-6 py-12 short:gap-4 short:py-8 md:px-12 lg:px-16"
      style={{ background: 'var(--color-ink)', color: 'var(--color-on-field)' }}
    >
      {/* First, because the answer to "is this payment real" depends on it. */}
      <OrderPicker orders={orders} selectedOrderId={selectedOrderId} onSelect={chooseOrder} />

      {/* The target. Focusable, activated by Enter or Space, so the whole screen
       * is reachable without a mouse. Its accessible name repeats both lines,
       * because a role="button" hides its own text from a screen reader. */}
      <div
        role="button"
        tabIndex={0}
        aria-label={`${UPLOAD_TITLE} — ${DROP_SUB}`}
        onClick={pick}
        onKeyDown={onKeyDown}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className="flex flex-1 cursor-pointer flex-col justify-center gap-6 p-8 short:gap-4 short:p-6 md:p-12"
        style={{
          border: `3px dashed ${dragging ? DASH_LIVE : DASH}`,
          background: dragging ? WASH : 'transparent',
        }}
      >
        <h1 className="text-verdict m-0" style={{ maxWidth: '13ch' }}>
          {UPLOAD_TITLE}
        </h1>
        <p
          className="text-lede m-0"
          style={{ color: 'var(--color-on-field-dim)', maxWidth: '34ch' }}
        >
          {DROP_SUB}
        </p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          take(pickImage(e.target.files), 'file')
          e.target.value = '' // so the same file can be chosen twice
        }}
      />

      {/* Preview and actions sit OUTSIDE the target: a screen reader would not
       * reach them inside it, and the file name is worth reading. */}
      <div className="flex flex-wrap items-center gap-4">
        {claim && (
          <>
            <img
              src={claim.url}
              alt="The screenshot you shared"
              className="h-24 w-24 shrink-0 object-cover"
              style={{ border: `3px solid ${DASH_LIVE}` }}
            />
            {/* `minWidth: 0` inline, not `min-w-0`: the spacing scale has no 0 step,
              * so that utility generates nothing — and without it a long file name
              * refuses to shrink and pushes the buttons off the row. */}
            <div style={{ minWidth: 0 }}>
              <b className="block truncate text-lg font-bold" style={{ maxWidth: '28ch' }}>
                {claim.file.name}
              </b>
              <span className="cap block" style={{ color: 'var(--color-on-field-dim)' }}>
                ready to check
              </span>
            </div>
          </>
        )}

        {claim ? (
          <>
            {/* Focused by the effect above the moment it becomes available, so a
              * paste is followed by one Enter and nothing else.
              *
              * Really disabled, not `aria-disabled`: a merchant who presses it and
              * gets nothing learns less than one who can see it is not available
              * yet. The cost is that a disabled control is not focusable, so the
              * reason cannot be announced from the button itself — which is why
              * the caption beside it carries it in text as well. */}
            <button
              ref={submitRef}
              type="button"
              disabled={!ready}
              aria-describedby={hintId}
              className={BUTTON_CLASS}
              style={{
                ...BUTTON,
                opacity: ready ? 1 : 0.6,
                cursor: ready ? 'pointer' : 'not-allowed',
              }}
              onClick={submit}
            >
              Check this payment
            </button>
            <button type="button" className={BUTTON_CLASS} style={BUTTON} onClick={clear}>
              Choose another
            </button>
          </>
        ) : (
          <button type="button" className={BUTTON_CLASS} style={BUTTON} onClick={pick}>
            Choose a screenshot
          </button>
        )}

        {/* `aria-live` because this line CHANGES — a screenshot arriving turns the
          * paste hint into the reason the check cannot run yet, and a merchant on
          * a screen reader would otherwise never hear that it had. */}
        <span
          id={hintId}
          aria-live="polite"
          className="cap"
          style={{ color: 'var(--color-on-field-dim)' }}
        >
          {hint}
        </span>
      </div>

      {message && (
        <p
          role="alert"
          className="text-lede m-0"
          style={{ color: 'var(--color-pale-red)', maxWidth: '40ch' }}
        >
          {message}
        </p>
      )}

      {rail.length > 0 && (
        <div className="flex flex-col gap-4">
          <p className="cap m-0" style={{ color: 'var(--color-on-field-dim)' }}>
            {UPLOAD_HINT}
          </p>
          <div className="flex flex-wrap gap-4">
            {rail.map((demo) => {
              // Rule 3: the glyph comes through the lookup, never by name.
              const Glyph = presentation(demo.status).Glyph
              return (
                <button
                  key={demo.id}
                  type="button"
                  className={BUTTON_CLASS}
                  style={BUTTON}
                  onClick={() => onSubmit({ kind: 'demo', verificationId: demo.id })}
                >
                  <Glyph size={24} />
                  {demo.label}
                </button>
              )
            })}
          </div>
        </div>
      )}

      <p className="cap m-0" style={{ color: 'var(--color-on-field-dim)', maxWidth: '60ch' }}>
        {UPLOAD_META}
      </p>
    </section>
  )
}
