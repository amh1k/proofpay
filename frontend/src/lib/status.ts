/**
 * THE status lookup. One table. Everything on screen reads from it.
 *
 * Word, field colour, ink, supporting ink, fill polarity and glyph all come from
 * the same row, so a red field with a "Payment received" word, or a mismatch
 * wearing the verified tick, is not something a component can accidentally build.
 *
 * Colours are `var(--color-…)` references, not hex, so `src/theme.css` stays the
 * single source of colour truth. They drop straight into an inline style:
 *
 *     const p = presentation(result.status)
 *     <section style={{ background: p.field, color: p.ink }}>
 *       <p.Glyph size={56} />
 *       <h1 className="text-verdict">{p.word}</h1>
 *
 * Rule 2: word + silhouette + fill polarity carry the status BEFORE colour.
 * Apply `grayscale(1)` to the result screen and all five must still be tellable
 * apart. Do not add a colour-only distinction to this table.
 *
 * Rule 1: there is deliberately no `confidence`, no `risk` and no severity here.
 * A second HIGH/MEDIUM/LOW pill is a fraud score with better manners.
 */

import {
  DuplicateGlyph,
  MismatchGlyph,
  NotFoundGlyph,
  ReviewGlyph,
  VerifiedGlyph,
  type GlyphComponent,
} from '../components/StatusGlyph'
import type { VerificationStatus } from '../types'

/**
 * `filled` — a full-bleed coloured field, white ink.
 * `hollow` — white ground, ink text, dashed rules, outlined glyph. UNMATCHED only.
 *   This is the polarity flip that keeps "not found" from reading as an accusation.
 */
export type FieldPolarity = 'filled' | 'hollow'

export interface StatusPresentation {
  status: VerificationStatus
  /** The one very large word. Set in `text-verdict`, max-width ~13ch. */
  word: string
  /** Two or three words, for list rows, nav strips and demo buttons. */
  short: string
  /** Full-bleed field behind the verdict. */
  field: string
  /** Text colour on that field. */
  ink: string
  /** Lower-emphasis ink: captions, the struck-through claimed figure, meta rules. */
  support: string
  /** Hairlines and the 3px button borders on that field. */
  rule: string
  polarity: FieldPolarity
  /** True only for UNMATCHED: rules are dashed, never solid. */
  dashed: boolean
  /** The glyph. Bound HERE and nowhere else. Render as `<p.Glyph size={56} />`. */
  Glyph: GlyphComponent
  /**
   * Whether this verdict lets the merchant hand over the goods. Drives which pair
   * of actions the result screen offers — never how prominently it draws them.
   * Rule 5: the two buttons are always the same visual weight.
   */
  approvable: boolean
}

const WHITE = 'var(--color-on-field)'
const WHITE_DIM = 'var(--color-on-field-dim)'

export const STATUS_PRESENTATION: Readonly<Record<VerificationStatus, StatusPresentation>> = {
  VERIFIED: {
    status: 'VERIFIED',
    word: 'Payment received',
    short: 'Verified',
    field: 'var(--color-verified)',
    ink: WHITE,
    support: 'var(--color-pale-green)',
    rule: WHITE,
    polarity: 'filled',
    dashed: false,
    Glyph: VerifiedGlyph,
    approvable: true,
  },

  SUSPICIOUS: {
    // "does not match", never "fraud". The transaction is real; the amount was
    // edited. The product's whole claim rests on that distinction.
    status: 'SUSPICIOUS',
    word: 'Amount does not match',
    short: 'Amount edited',
    field: 'var(--color-mismatch)',
    ink: WHITE,
    support: 'var(--color-pale-red)',
    rule: WHITE,
    polarity: 'filled',
    dashed: false,
    Glyph: MismatchGlyph,
    approvable: false,
  },

  DUPLICATE: {
    // Same field as a mismatch on purpose. The silhouette is what separates them.
    status: 'DUPLICATE',
    word: 'Already counted',
    short: 'Already used',
    field: 'var(--color-duplicate)',
    ink: WHITE,
    support: 'var(--color-pale-red)',
    rule: WHITE,
    polarity: 'filled',
    dashed: false,
    Glyph: DuplicateGlyph,
    approvable: false,
  },

  NEEDS_REVIEW: {
    status: 'NEEDS_REVIEW',
    word: 'Not sure about this one',
    short: 'Needs checking',
    field: 'var(--color-review)',
    ink: WHITE,
    // No pale amber exists in the verified palette, so this is white at lower
    // emphasis — an alpha of an approved colour, not a new hue.
    support: WHITE_DIM,
    rule: WHITE,
    polarity: 'filled',
    dashed: false,
    Glyph: ReviewGlyph,
    approvable: false,
  },

  UNMATCHED: {
    // Rule 4. No fill, no colour, dashed rule, hollow glyph. Not an accusation.
    status: 'UNMATCHED',
    word: 'No matching payment yet',
    short: 'Not found yet',
    field: 'var(--color-notfound)',
    ink: 'var(--color-on-paper)',
    support: 'var(--color-on-paper-dim)',
    rule: 'var(--color-rule)',
    polarity: 'hollow',
    dashed: true,
    Glyph: NotFoundGlyph,
    approvable: false,
  },
}

/** The one accessor. Prefer this over indexing the table by hand. */
export function presentation(status: VerificationStatus): StatusPresentation {
  return STATUS_PRESENTATION[status]
}

/**
 * Worst first. Use for sorting a list of verifications so the merchant sees what
 * needs a decision before what does not.
 */
export const STATUS_ORDER: readonly VerificationStatus[] = [
  'SUSPICIOUS',
  'DUPLICATE',
  'NEEDS_REVIEW',
  'UNMATCHED',
  'VERIFIED',
]

/** Index into `STATUS_ORDER`, for `sort((a, b) => severity(a) - severity(b))`. */
export function severity(status: VerificationStatus): number {
  return STATUS_ORDER.indexOf(status)
}
