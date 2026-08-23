/**
 * The entry point.
 *
 * The merchant arrives here holding a screenshot the customer sent on WhatsApp.
 * Three ways in, and they are not equal:
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

import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, DragEvent, KeyboardEvent, ReactElement } from 'react'
import { UPLOAD_HINT, UPLOAD_META, UPLOAD_TITLE } from '../lib/copy'
import { presentation } from '../lib/status'
import type { VerificationStatus } from '../types'

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
 * The demo rail, in the order a demo is told: the edited amount first, because it
 * is the one nobody believes until they see it, then the already-used receipt,
 * then the payment that has simply not landed yet.
 *
 * The labels come from `presentation(status).short`, never from a string here —
 * the words for a status live in exactly one table.
 */
const DEMO_ORDER: readonly VerificationStatus[] = ['SUSPICIOUS', 'DUPLICATE', 'UNMATCHED']

function demoRail(demos: DemoClaim[]): DemoClaim[] {
  const picked: DemoClaim[] = []
  for (const status of DEMO_ORDER) {
    const found = demos.find((d) => d.status === status)
    if (found) picked.push(found)
  }
  // If the fixture set ever changes shape, show something rather than nothing.
  return picked.length > 0 ? picked : demos.slice(0, 3)
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

export function UploadScreen({ onSubmit, demos, error }: UploadScreenProps): ReactElement {
  const inputRef = useRef<HTMLInputElement>(null)
  /** The live object URL, so exactly one exists and it is always revoked. */
  const urlRef = useRef<string | null>(null)

  const [claim, setClaim] = useState<Claim | null>(null)
  const [dragging, setDragging] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

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
    if (!claim) return
    const { file, kind } = claim
    onSubmit(kind === 'paste' ? { kind: 'paste', file } : { kind: 'file', file })
  }

  const rail = demoRail(demos)
  const message = notice ?? error

  return (
    <section
      className="flex flex-1 flex-col gap-8 px-6 py-12 short:gap-6 short:py-8 md:px-12 lg:px-16"
      style={{ background: 'var(--color-ink)', color: 'var(--color-on-field)' }}
    >
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
            {/* Focused on arrival, so a paste is followed by one Enter and nothing else. */}
            <button type="button" autoFocus className={BUTTON_CLASS} style={BUTTON} onClick={submit}>
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

        <span className="cap" style={{ color: 'var(--color-on-field-dim)' }}>
          {PASTE_HINT}
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
