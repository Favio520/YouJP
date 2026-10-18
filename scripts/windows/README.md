# YouJP for Windows

Open **YouJP.exe** in the project root. It has a native icon and opens the WPF
interface without a console. You can create a shortcut, but keep the executable
beside the project folders: it is not a standalone installer.

The window contains **Your session**, **Settings**, and **Activity**. Its status
distinguishes a ready backend from a connected browser tab. Choose **English**
or **Español** in Settings; this preference is saved separately from the browser
extension's interface and translation languages.

Closing the window leaves YouJP in the tray. **Exit and stop** stops the backend
started by that launcher. A backend started by another application is not stopped.
Technical logs and external diagnostic messages keep their original wording.

`YouJP.cmd` also works when the executable has not been built. **Prepare / update**
prepares dependencies, builds the extension, and creates the launcher. When updating
an old extension with a different ID, remove it from `chrome://extensions`, load the
new build, and restart the backend.

## Distribution

Users normally install `YouJP-Setup-<version>.exe` from a GitHub release. It installs per user
under `%LOCALAPPDATA%\Programs\YouJP` and, optionally, runs `Install-FirstRun.ps1` (which wraps
`Setup.ps1` in a visible window and logs to `.youjp/install-firstrun.log`). `Setup.ps1` prints
`[n/5]` stage markers, shown in **Activity** when started from the launcher. Packages contain
the already-built extension, so `Setup.ps1` skips Node.js when `extension/package.json` is absent.

`Package-Release.ps1` builds the zip, the installer (`installer/YouJP.iss`, Inno Setup 6) and
`SHA256SUMS.txt` into `dist/`. See `docs/publishing.md` for releases and store publication.

## Development

The launcher uses WPF, Windows PowerShell 5.1, and the .NET Framework compiler
included with Windows. No additional UI SDK is required.

```powershell
# Build icons and executable with YouJP closed
powershell -NoProfile -ExecutionPolicy Bypass -STA -File scripts/windows/Build-Launcher.ps1

# Check states, profiles, XAML, language switching, and executable without models
powershell -NoProfile -ExecutionPolicy Bypass -STA -File scripts/windows/Test-Launcher.ps1

# Isolated preview window
.\YouJP.exe --preview --preview-state=ready

# Render the XAML to local images without capturing the desktop
powershell -NoProfile -ExecutionPolicy Bypass -STA -File scripts/windows/Render-Preview.ps1 -State ready -Language en
```

`YouJP.xaml` defines the interface, `LauncherState.ps1` derives presentation state,
and `YouJP.ps1` supervises processes. `Localization.ps1` and `locales/en.json`
provide English labels. `Launcher.cs` hosts the controller inside `YouJP.exe`
on an STA thread.

## Visual assets

The launcher and the extension share the dark "Sumi" system: ink (`#0E0F13`),
washi-paper text (`#F4F0E8`), one vermilion accent for what is active or
clickable (`#FF6A4D`; `#D23A20` behind white text on filled buttons), gold
(`#F7D794`) for translation and work in progress, and green (`#73D69F`) for
ready. The sidebar marks the current page with a vermilion bar. The session
cover lays the Fuji landscape under an ink gradient so the text reads on ink
and the artwork stays in dusk instead of glaring. Cards are flat, with 14 px
corners and hairline borders. `YouJP.ps1` paints each engine state with the
same values. The default window is 1180 × 850, bounded by the available desktop
area; shorter windows scroll their content.

CI renders the four pages in six states and both languages with a sample
history and uploads them as the `youjp-launcher-previews` artifact. For an
interactive review of the extension's production components without models or
audio capture, run `npm.cmd run preview:ui` from `extension` and open
`http://127.0.0.1:4178`. Review criteria and results are recorded in
`docs/ui-redesign.md`.

`assets/app-icon-sumi-e.png` is the emblem: the dinosaur with headphones and a
sakura ear cup. `Build-Icons.ps1` scales it with WPF and writes `app-logo.png`,
`youjp-logo.ico` (16 to 256 pixels, for the window, executable and tray) and the
extension icons in `extension/public/icon`, so all three share one mark.
`Build-Launcher.ps1` runs it before compiling `YouJP.exe`.

`assets/mascot-pastel.png` is the transparent mascot with headphones and a
hiragana card. `assets/fuji-pastel.png` is the Fuji and sakura landscape.
Both files are the original artwork supplied with the earlier pastel UI
reference; the dark cover keeps them unmodified.
