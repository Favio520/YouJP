# YouJP pastel UI review

Reviewed on 30 September 2026. Scope: Windows launcher, live subtitles, history,
dictionary, settings, and screen translation.

## Design

The supplied mockup defines the direction: warm paper `#FFF9F2`, ink `#25364A`,
coral `#FF705E`, lilac `#B9A2F4`, and mint `#C8E8D3`. Major cards use 22 px
corners and restrained shadows. The original landscape and transparent mascot
were copied to `scripts/windows/assets/fuji-pastel.png` and
`scripts/windows/assets/mascot-pastel.png` without image modifications.

Windows uses a light sidebar, ink/coral wordmark, illustrated session cover,
four separate pastel tiles, mint step markers, and a lilac activity card.
Sakura decorations yield to navigation when vertical space is limited. Alerts
use peach surfaces and dark coral text. Primary coral buttons use ink labels
to keep small text readable. The emblem follows the same ink/coral palette.
The default window is 1180 × 850, capped by the desktop work area.

Extension study panels use warm paper with mint, lilac, and peach headers.
History translations, dictionary readings, and focus rings use a deeper violet
derived from the lilac accent. Video subtitles keep a dark, rounded material
with white Japanese and mint translation so bright moving frames remain legible.
The OCR panel shares the paper palette. Fonts and icons require no remote requests.

## Quality iterations

1. Recreated the reference composition and integrated both supplied artwork files.
2. Corrected the wordmark, refined typography and icon shapes, reduced the width
   of the alert to preserve the landscape, and increased the mascot's presence.
3. Reviewed compact layouts and localized labels. Clipped decorative sakura to
   the available sidebar space and shortened repeated activity descriptions.
4. Improved small-player dictionary height and internal spacing after inspection
   showed the meaning below the initial visible area. Increased contrast of
   previous and tentative subtitle text; hover feedback preserves label contrast.

## Evidence

- Extension: 87 existing tests pass; TypeScript, lint, and production build pass.
- Windows: native executable build and `Test-Launcher.ps1` pass. Smoke checks load
  56 named controls, seven states, and three pages, including language changes.
- Rendered the seven Windows states across three pages and three content sizes:
  1180 × 828, 1120 × 778, and 880 × 580. Error and first-run screens were also
  rendered in English. Representative renders were visually inspected.
- Browser review mounts the production Overlay, SettingsPanel, TranscriptPanel,
  and WordInspector with simulated messages and storage. Large and 640 px players
  were inspected. Default history and dictionary panels remain inside the player
  and do not overlap each other. The compact dictionary shows the sample meaning
  without needing to scroll past the headword.
- A keyboard arrow changed Japanese text from 28 to 30 px immediately. Reset
  restored 28 px while preserving the English interface and Spanish translation.
  Escape closed the settings panel. Connection error and empty history were reviewed.
- Reduced-motion rules remain active; UI review reported no console errors.

Selected color-pair calculations:

| Text / background | Ratio |
| --- | ---: |
| Ink / warm paper | 11.78:1 |
| Secondary / warm paper | 5.20:1 |
| Primary action ink / coral | 4.53:1 |
| Ink / lilac | 5.59:1 |
| Ink / mint | 9.35:1 |
| Violet / warm paper | 6.23:1 |
| Alert text / peach | 5.17:1 |
| Translation / soft material over white | 4.76:1 |

These are selected calculations, not a full accessibility certification.
Arbitrary video frames and user-selected subtitle backgrounds need separate review.

## Review locally

From `extension`, run `npm.cmd run preview:ui`, then open
`http://127.0.0.1:4178`. The lab uses simulated data; it does not capture audio
or start models. Its landscape belongs to the example video, not the extension's
production overlay. Native renders and browser screenshots are under
`.youjp/ui-previews/`.

Reopen `YouJP.exe` for the Windows interface. Reload
`extension/.output/chrome-mv3` and the YouTube tab for the rebuilt extension.

The award references express the craft target; an award itself depends on a jury.
Live Chrome/YouTube audio capture, real fullscreen transitions, and native Windows
keyboard input remain outside this isolated visual review.
