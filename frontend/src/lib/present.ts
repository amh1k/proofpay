/**
 * Projector mode: `?present=1`.
 *
 * A judge sits six metres from a screen the presenter cannot control. The obvious
 * fix — Ctrl+= in the browser — is a trap: browser zoom shrinks the CSS viewport,
 * so 1280px of projector at 125% becomes a 1024px layout, and at 150% a 853px
 * one. Zoom in far enough on stage and the phone breakpoint fires, the two
 * amounts stack, and the sign you rehearsed is not the sign on the wall.
 *
 * So the size is raised from inside instead. This stamps `data-present="on"` on
 * the root element; `theme.css` answers it by lifting the root font size and the
 * four signage type steps. The viewport never changes, so every breakpoint stays
 * exactly where it was.
 *
 * It is applied before React renders (see `main.tsx`) so there is no flash of the
 * small layout, and it is a URL parameter rather than a setting so the presenter
 * can put the projector link in a bookmark and never touch it again.
 */

/** `?present=1`, `?present=on`, `?present`. `?present=0` and `?present=false` are off. */
export const PRESENT_PARAM = 'present'

const OFF: ReadonlySet<string> = new Set(['0', 'false', 'no', 'off'])

export function presentRequested(search: string): boolean {
  const value = new URLSearchParams(search).get(PRESENT_PARAM)
  if (value === null) return false
  return !OFF.has(value.trim().toLowerCase())
}

/**
 * Stamp (or clear) the attribute the stylesheet keys off. Returns what it did, so
 * a caller can say so without reading the DOM back.
 */
export function applyPresentMode(doc: Document, search: string): boolean {
  const on = presentRequested(search)
  if (on) doc.documentElement.setAttribute('data-present', 'on')
  else doc.documentElement.removeAttribute('data-present')
  return on
}
