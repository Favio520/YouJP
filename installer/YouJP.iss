; Instalador de YouJP para Windows (Inno Setup 6).
; Lo compila scripts/windows/Package-Release.ps1, que define:
;   AppVersion, SourceDir (carpeta preparada) y OutputDir.
; Opcionales: ChromeStoreId / EdgeStoreId, para registrar la extensión publicada en las tiendas.

#ifndef AppVersion
  #error Define AppVersion (compila con scripts/windows/Package-Release.ps1).
#endif
#ifndef SourceDir
  #error Define SourceDir.
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{3056675B-85D5-43CC-AFE7-6B8DBB800061}
AppName=YouJP
AppVersion={#AppVersion}
AppPublisher=YouJP
VersionInfoVersion={#AppVersion}
; Por usuario y sin administrador: el entorno de Python, los modelos y los datos
; se escriben dentro de la carpeta de instalación.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\YouJP
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir={#OutputDir}
OutputBaseFilename=YouJP-Setup-{#AppVersion}
SetupIconFile={#SourceDir}\scripts\windows\assets\youjp-logo.ico
UninstallDisplayIcon={app}\YouJP.exe
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
spanish.TaskPrepare=Descargar y preparar los modelos ahora (recomendado, hasta ~5 GB)
spanish.TaskPrepareHint=Sin esto, YouJP te pedirá pulsar "Preparar / actualizar" la primera vez.
spanish.RunPrepare=Preparando YouJP (modelos y dependencias)
spanish.RunLaunch=Abrir YouJP
spanish.RunOllama=Abrir la página de descarga de Ollama (opcional, traducción de más calidad)
spanish.RunExtension=Abrir la carpeta de la extensión para cargarla en Chrome o Edge
english.TaskPrepare=Download and prepare the models now (recommended, up to ~5 GB)
english.TaskPrepareHint=Otherwise YouJP will ask you to press "Prepare / update" the first time.
english.RunPrepare=Preparing YouJP (models and dependencies)
english.RunLaunch=Open YouJP
english.RunOllama=Open the Ollama download page (optional, higher-quality translation)
english.RunExtension=Open the extension folder to load it in Chrome or Edge

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "prepare"; Description: "{cm:TaskPrepare}"; GroupDescription: "{cm:TaskPrepareHint}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\YouJP"; Filename: "{app}\YouJP.exe"
Name: "{autodesktop}\YouJP"; Filename: "{app}\YouJP.exe"; Tasks: desktopicon

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\windows\Install-FirstRun.ps1"""; \
  WorkingDir: "{app}"; StatusMsg: "{cm:RunPrepare}"; Tasks: prepare; Flags: waituntilterminated
Filename: "{app}\YouJP.exe"; Description: "{cm:RunLaunch}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\extension\.output\chrome-mv3"; Description: "{cm:RunExtension}"; Flags: shellexec postinstall skipifsilent unchecked
Filename: "https://ollama.com/download"; Description: "{cm:RunOllama}"; Flags: shellexec postinstall skipifsilent unchecked

#ifdef ChromeStoreId
[Registry]
; Chrome ofrece activar la extensión publicada la próxima vez que se abre.
Root: HKCU; Subkey: "Software\Google\Chrome\Extensions\{#ChromeStoreId}"; ValueType: string; \
  ValueName: "update_url"; ValueData: "https://clients2.google.com/service/update2/crx"; Flags: uninsdeletekey
#endif
#ifdef EdgeStoreId
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Edge\Extensions\{#EdgeStoreId}"; ValueType: string; \
  ValueName: "update_url"; ValueData: "https://edge.microsoft.com/extensionwebstorebase/v1/crx"; Flags: uninsdeletekey
#endif

[UninstallDelete]
; Lo que crea la preparación y el uso no está en la lista de ficheros instalados.
Type: filesandordirs; Name: "{app}\.youjp"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\backend"
Type: files; Name: "{app}\.env"
