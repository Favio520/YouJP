# YouJP "Sumi" extension UI

Reviewed on 17 October 2026. Scope: the browser extension's live subtitles,
history, dictionary, settings, player buttons, and screen translation. The
Windows launcher keeps the pastel system described in
`scripts/windows/README.md`; it is unchanged by this redesign.

## Why it changed

The previous extension panels used the launcher's light, warm paper. Over a
video they were the brightest thing on screen: in dark scenes they dazzled, and
they covered more of the frame visually than they did physically. The new
system treats every panel as part of the player instead of a sheet laid over
it.

## Design

"Sumi" (ink): dark glass, washi-paper text, and one vermilion accent (朱).

| Token | Value | Use |
| --- | --- | --- |
| Glass | `rgba(17,18,23,.9)` + 18 px blur | History, dictionary, settings, OCR panels |
| Text | `#F4F0E8` | Primary text, selected segmented option |
| Secondary / tertiary | `#BDB7AD` / `#9A958C` | Hints, metadata, timestamps |
| Vermilion | `#FF6A4D` | Interactive and active state only: selected word, open panel, focus ring, progress |
| Deep vermilion | `#D23A20` | Filled primary action and panel seals, with white text |
| Gold | `#F7D794` | Translations everywhere, readings in the dictionary |
| Green | `#73D69F` | "Ready" and "common word" |

Each colour means one thing: vermilion is "you can act here / this is active",
gold is "translation or reading". Japanese stays white so the eye can jump
between languages without reading them.

- **Panel structure.** All three study panels share one header: a vermilion
  hanko seal with the panel's kanji (記 history, 辞 dictionary, 調 settings), a
  title, a short subtitle, and quiet icon buttons. Panels are told apart by the
  seal, not by background colour. The header remains the drag handle.
- **Subtitles.** The ribbon band is darker and tighter (12 px corners); the
  translation is gold below a hairline. An empty band is no longer drawn while
  starting, after an error, or between sentences of a prepared video.
- **Paper skin.** Washi card with ink text, vermilion furigana, and indigo
  translation with an outlined language tag.
- **Grammar skin.** Same underline categories, retuned to the new palette; the
  legend uses the glass material.
- **Toolbar.** One glass pill for every skin, dimmed to 55 % until the pointer
  reaches the subtitles or focus enters it. An open panel shows its tool in
  vermilion with a small bar.
- **History.** Rows without dividers; the timestamp reveals a play mark on
  hover; the sentence playing in a prepared video gets a vermilion edge.
- **Dictionary.** Large mincho headword over a faint vermilion sun, gold
  reading, outlined tags, numbered senses in vermilion.
- **Settings.** A sticky section index (Video, Style, Reading, Language,
  Interface) scrolls only the panel, never the YouTube page. Sections are
  numbered. Sliders show the travelled part in vermilion; the selected
  segmented option is paper on ink. The live preview remains at the top.
- **Compact layouts.** Panels respond to their own width with container
  queries, so two panels side by side in a small player compact even on a large
  screen. In a short player the settings header and preview shrink.
- **Player buttons** use paper white at rest, a vermilion progress ring while
  translating, and a vermilion tint while settings are open.
- Fonts and icons are local; nothing is fetched from the network.

## Quality iterations

1. Rendered the production components in the preview lab and compared them
   with the previous pastel renders at 1400 × 1000 and with a 640 px player.
2. The settings index shrank to a sliver because it was a shrinking flex item;
   fixed with `flex: none`.
3. In the compact player the dictionary meaning fell below the visible area.
   Added container queries for narrow panels and a height query for short
   settings docks.
4. The English index clipped "Interface"; tightened chip spacing so all five fit.
5. Raised gold and tertiary text after measuring them against the worst case
   (translucent material over a white frame).
6. Removed the empty subtitle band that appeared below status pills.

## Evidence

- Extension: 93 existing tests pass; TypeScript, Biome lint, and production
  build pass.
- Browser review (Chromium via Playwright) of the preview lab: active session,
  starting, error, empty history, history with dictionary, settings (scrolled,
  three skins, English interface), compact player with both panels, compact
  settings, and the OCR selector and result. No console errors.

Contrast, with translucent layers composited over a white frame (the worst case
for dark materials):

| Text / background | Ratio |
| --- | ---: |
| Text / glass | 12.61:1 |
| Secondary / glass | 7.20:1 |
| Tertiary / glass | 4.81:1 |
| Gold / glass | 10.31:1 |
| Vermilion / glass | 5.07:1 |
| White / deep vermilion (primary action) | 4.81:1 |
| Japanese / soft band | 6.49:1 |
| Gold translation / soft band | 4.67:1 |
| Paper skin: ink / washi | 15.20:1 |
| Paper skin: translation / washi | 8.32:1 |
| Paper skin: furigana / washi | 4.79:1 |

These are selected calculations, not a full accessibility certification.
Arbitrary video frames with the "None" background rely on the text outline.

## Review locally

From `extension`, run `npm.cmd run preview:ui`, then open
`http://127.0.0.1:4178`. The lab uses simulated data; it does not capture audio
or start models. "Recorte (OCR)" opens the real region selector with a canned
result. Its landscape belongs to the example video, not the extension.

Reload `extension/.output/chrome-mv3` and the YouTube tab for the rebuilt
extension.

Live Chrome/YouTube audio capture, real fullscreen transitions, and the actual
YouTube control bar remain outside this isolated visual review.
