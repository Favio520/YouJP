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

The interface uses an ivory background, jade cover, coral actions, and compact
peach, mint, blue, and lavender status cards. Settings and Activity retain their
existing controls and behavior.

`assets/BrandLogo.xaml` defines the headphones and dialogue emblem.
`Build-Icons.ps1` generates `app-logo.png` and `youjp-logo.ico` at sizes from
16 to 256 pixels for the window, executable, and tray. It does not change the
extension icons. Previous assets are retained.

`assets/mascot-design-b.png` is the transparent mascot with headphones and a
hiragana card. `assets/fuji-design-b.png` is the jade and coral landscape.
