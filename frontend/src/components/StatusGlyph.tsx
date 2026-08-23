/**
 * The five glyphs.
 *
 * Rule 3: the silhouettes must DIFFER. A matching icon family (CircleCheck /
 * CircleX / CircleAlert) is three identical discs through a projector, which is
 * exactly the failure this product cannot afford. So:
 *
 *   SUSPICIOUS   filled triangle
 *   VERIFIED     filled circle, check cut out of it
 *   DUPLICATE    two overlapping squares, seam between them
 *   NEEDS_REVIEW filled rounded square, question cut out of it
 *   UNMATCHED    HOLLOW outlined circle with clock hands — no fill, ever
 *
 * Every glyph paints in `currentColor`, so it takes the ink of whatever field it
 * sits on. Interior detail is a real hole (an SVG mask), not a second colour, so
 * the field colour shows through and the glyph works on any ground.
 *
 * These are shapes, not decisions. The status -> glyph binding lives in exactly
 * ONE place, `STATUS_PRESENTATION` in `src/lib/status.ts`. Reach a glyph through
 * `presentation(status).Glyph`; never import one of these by name to pick it
 * yourself, or a mismatch becomes representable again.
 */

import { useId, type ReactElement } from 'react'

/**
 * `useId()` returns punctuation that differs between React versions — colons in
 * 18, guillemets in 19 — and neither is safe inside `url(#...)`. Strip everything
 * that is not a plain id character.
 */
function maskId(raw: string): string {
  return `pp${raw.replace(/[^A-Za-z0-9_-]/g, '')}`
}

export interface GlyphProps {
  /** Edge length in px. The sign uses 56; list rows use 20. */
  size?: number
  /**
   * Accessible name. Pass `null` (the default) when the glyph sits beside the
   * verdict word, which already says it — a second announcement is noise.
   */
  label?: string | null
  className?: string
}

/** Every glyph has this shape, so they are interchangeable through the lookup. */
export type GlyphComponent = (props: GlyphProps) => ReactElement

function frame(
  size: number,
  label: string | null | undefined,
  className: string | undefined,
  children: ReactElement,
): ReactElement {
  const named = typeof label === 'string' && label.length > 0
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className={className}
      role={named ? 'img' : undefined}
      aria-label={named ? label : undefined}
      aria-hidden={named ? undefined : true}
      focusable="false"
    >
      {children}
    </svg>
  )
}

/** SUSPICIOUS — a filled triangle. The only pointed silhouette in the set. */
export function MismatchGlyph({ size = 56, label, className }: GlyphProps): ReactElement {
  const id = maskId(useId())
  return frame(
    size,
    label,
    className,
    <>
      <mask id={id}>
        <path d="M12 1.6 L23.2 21.4 H0.8 Z" fill="#fff" />
        <rect x="10.9" y="8.6" width="2.2" height="6.4" rx="1.1" fill="#000" />
        <rect x="10.9" y="16.4" width="2.2" height="2.4" rx="1.1" fill="#000" />
      </mask>
      <rect x="0" y="0" width="24" height="24" fill="currentColor" mask={`url(#${id})`} />
    </>,
  )
}

/** VERIFIED — a filled disc with the check cut out of it. */
export function VerifiedGlyph({ size = 56, label, className }: GlyphProps): ReactElement {
  const id = maskId(useId())
  return frame(
    size,
    label,
    className,
    <>
      <mask id={id}>
        <circle cx="12" cy="12" r="11.2" fill="#fff" />
        <path
          d="M6.4 12.3 L10.3 16.2 L17.8 8.2"
          stroke="#000"
          strokeWidth="2.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
      </mask>
      <rect x="0" y="0" width="24" height="24" fill="currentColor" mask={`url(#${id})`} />
    </>,
  )
}

/** DUPLICATE — two overlapping squares. Same field as a mismatch, different shape. */
export function DuplicateGlyph({ size = 56, label, className }: GlyphProps): ReactElement {
  const id = maskId(useId())
  return frame(
    size,
    label,
    className,
    <>
      <mask id={id}>
        {/* the square behind */}
        <rect x="1.4" y="1.4" width="13.6" height="13.6" rx="1.6" fill="#fff" />
        {/* punched back out again, one step larger, to leave a clean seam */}
        <rect x="7.4" y="7.4" width="16" height="16" rx="2.4" fill="#000" />
      </mask>
      <rect x="0" y="0" width="24" height="24" fill="currentColor" mask={`url(#${id})`} />
      {/* the square in front */}
      <rect x="9" y="9" width="13.6" height="13.6" rx="1.6" fill="currentColor" />
    </>,
  )
}

/** NEEDS_REVIEW — a filled rounded square with a question cut out of it. */
export function ReviewGlyph({ size = 56, label, className }: GlyphProps): ReactElement {
  const id = maskId(useId())
  return frame(
    size,
    label,
    className,
    <>
      <mask id={id}>
        <rect x="1.4" y="1.4" width="21.2" height="21.2" rx="3.2" fill="#fff" />
        <path
          d="M8.5 9.1 a3.5 3.5 0 1 1 3.9 3.5 v1.5"
          stroke="#000"
          strokeWidth="2.3"
          strokeLinecap="round"
          fill="none"
        />
        <rect x="11.1" y="16.4" width="2.4" height="2.4" rx="1.2" fill="#000" />
      </mask>
      <rect x="0" y="0" width="24" height="24" fill="currentColor" mask={`url(#${id})`} />
    </>,
  )
}

/**
 * UNMATCHED — a HOLLOW circle with clock hands. Rule 4: no fill, ever. The
 * outline polarity is what tells the merchant this is a wait, not an accusation.
 */
export function NotFoundGlyph({ size = 56, label, className }: GlyphProps): ReactElement {
  return frame(
    size,
    label,
    className,
    <>
      <circle cx="12" cy="12" r="10.4" fill="none" stroke="currentColor" strokeWidth="2.2" />
      <path
        d="M12 5.8 V12 l4 2.8"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>,
  )
}
