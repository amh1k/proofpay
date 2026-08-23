/**
 * The shape of a sign, written once.
 *
 * `Verdict.tsx` and `VerdictPositive.tsx` are two files because the three
 * rejections and the two non-accusations need different FACTS — not because they
 * are two designs. They had a copy of this class string each, and a copy drifts:
 * the moment one of them gains a gutter the other does not, the room can see it
 * when the demo moves between verdicts.
 */

/**
 * Full-bleed field, centred stack, and a gutter that keeps every word out of the
 * outer 5% of the viewport at 360px and at 1280px alike. `short:` tightens the
 * vertical padding on a 720p projector so the two actions stay above the fold.
 */
export const SIGN_CLASS =
  'flex flex-1 flex-col justify-center px-6 py-12 short:py-6 md:px-12 lg:px-16'

/**
 * The field fills the screen.
 *
 * A viewport measure, not a spacing value — the 4/8/12… scale governs the gaps
 * between things, and this is "as tall as the room can see".
 */
export const SIGN_MIN_HEIGHT = '72vh'
