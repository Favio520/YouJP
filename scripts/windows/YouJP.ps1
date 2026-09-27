param(
    [switch]$SmokeTest,
    [switch]$Preview,
    [ValidateSet('idle', 'ready', 'capturing', 'starting', 'setup', 'error', 'unprepared')]
    [string]$PreviewState = 'idle'
)
. (Join-Path $PSScriptRoot 'Common.ps1')
. (Join-Path $PSScriptRoot 'LauncherState.ps1')
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Net.Http

# La vista previa y la prueba aislada no inician ni controlan el backend.
$mutex = $null
if (-not ($SmokeTest -or $Preview)) {
    $hash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash(
        [Text.Encoding]::UTF8.GetBytes($script:ProjectRoot.ToLowerInvariant()))).Replace('-', '').Substring(0, 20)
    $mutex = [Threading.Mutex]::new($false, "Local\YouJP-$hash")
    if (-not $mutex.WaitOne(0)) {
        [Windows.MessageBox]::Show('YouJP ya está abierto. Busca su icono en la bandeja del sistema.', 'YouJP') | Out-Null
        $mutex.Dispose()
        exit 0
    }
}

$script:backendProcess = $null
$script:setupProcess = $null
$script:stopFile = $null
$script:stopRequestedAt = $null
$script:exitRequested = $false
$script:healthTask = $null
$script:health = $null
$script:healthChecked = $false
$script:failure = ''
$script:logPath = $null
$script:errorLogPath = $null
$script:previewKind = $PreviewState
$script:page = 'home'
$script:http = [Net.Http.HttpClient]::new()
$script:http.Timeout = [TimeSpan]::FromSeconds(2)
$script:appVersion = Get-YouJPVersion
$script:runtime = Get-YouJPRuntime

function Test-Installation {
    $marker = Join-Path $script:RuntimeDir 'installed-version'
    $python = Join-Path $script:ProjectRoot 'backend/.venv/Scripts/python.exe'
    return ((Test-Path -LiteralPath $marker) -and (Test-Path -LiteralPath $python) -and
        (Get-Content -LiteralPath $marker -Raw).Trim() -eq $script:appVersion)
}
$script:installed = Test-Installation

$markup = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'YouJP.xaml'))
$reader = [Xml.XmlNodeReader]::new([xml]$markup)
try { $window = [Windows.Markup.XamlReader]::Load($reader) } finally { $reader.Close() }
$ui = @{}
foreach ($match in [regex]::Matches($markup, 'x:Name="([^"]+)"')) {
    $control = $window.FindName($match.Groups[1].Value)
    if ($control) { $ui[$match.Groups[1].Value] = $control }
}
$window.Title = 'YouJP ' + $script:appVersion
$window.Width = [Math]::Min(1100, [Windows.SystemParameters]::WorkArea.Width - 32)
$window.Height = [Math]::Min(800, [Windows.SystemParameters]::WorkArea.Height - 32)
$ui.VersionLabel.Text = 'YouJP  /  ' + $script:appVersion
$iconPath = Join-Path $PSScriptRoot 'assets/app-icon.png'
if (Test-Path -LiteralPath $iconPath) {
    $brandImage = [Windows.Media.Imaging.BitmapImage]::new([Uri]$iconPath)
    $ui.BrandIcon.Source = $brandImage
    $window.Icon = $brandImage
}
$mascotPath = Join-Path $PSScriptRoot 'assets/mascot-dino.png'
if (Test-Path -LiteralPath $mascotPath) {
    $ui.MascotImage.Source = [Windows.Media.Imaging.BitmapImage]::new([Uri]$mascotPath)
}
if ($Preview) {
    $window.Title += ' — Vista previa'
    $ui.PreviewLabel.Visibility = 'Visible'
    $ui.FooterHint.Text = 'Vista previa del diseño. Los controles no inician descargas ni procesos.'
}

function Show-Page([string]$Page) {
    $script:page = $Page
    $ui.HomePage.Visibility = 'Collapsed'
    $ui.SettingsPage.Visibility = 'Collapsed'
    $ui.ActivityPage.Visibility = 'Collapsed'
    switch ($Page) {
        'home' {
            $ui.HomePage.Visibility = 'Visible'; $ui.NavHome.IsChecked = $true
            $ui.PageEyebrow.Text = '今日の日本語  /  TU JAPONÉS DE HOY'
            $ui.PageTitle.Text = 'Tu dosis de japonés'; $ui.PageDescription.Text = 'Un poco de japonés. A tu ritmo.'
        }
        'settings' {
            $ui.SettingsPage.Visibility = 'Visible'; $ui.NavSettings.IsChecked = $true
            $ui.PageEyebrow.Text = '準備  /  TODO A PUNTO'
            $ui.PageTitle.Text = 'Configuración'; $ui.PageDescription.Text = 'Prepara una vez. Aprende cada día.'
        }
        'activity' {
            $ui.ActivityPage.Visibility = 'Visible'; $ui.NavActivity.IsChecked = $true
            $ui.PageEyebrow.Text = '記録  /  DETRÁS DE CADA FRASE'
            $ui.PageTitle.Text = 'Actividad'; $ui.PageDescription.Text = 'El estado de YouJP y sus últimos registros.'
            Update-Log
        }
    }
    if (-not $SmokeTest) {
        $pageControl = switch ($Page) { 'home' { $ui.HomePage } 'settings' { $ui.SettingsPage } 'activity' { $ui.ActivityPage } }
        $fade = [Windows.Media.Animation.DoubleAnimation]::new(0, 1, [Windows.Duration]::new([TimeSpan]::FromMilliseconds(160)))
        $pageControl.BeginAnimation([Windows.UIElement]::OpacityProperty, $fade)
    }
}

function Get-PanelState {
    if ($Preview -or $SmokeTest) {
        return Get-YouJPPanelState -Installed ($script:previewKind -ne 'unprepared') -Checked $true `
            -Owned ($script:previewKind -in @('starting', 'ready', 'capturing')) `
            -SettingUp ($script:previewKind -eq 'setup') -Ready ($script:previewKind -in @('ready', 'capturing')) `
            -Sessions $(if ($script:previewKind -eq 'capturing') { 1 } else { 0 }) `
            -Failure $(if ($script:previewKind -eq 'error') { 'No se pudo cargar el modelo. Revisa el registro y vuelve a intentarlo.' } else { '' })
    }
    $owned = $script:backendProcess -and -not $script:backendProcess.HasExited
    $settingUp = $script:setupProcess -and -not $script:setupProcess.HasExited
    $ready = Test-YouJPHealth $script:health
    $sessions = 0
    if ($ready -and 'sessions' -in $script:health.PSObject.Properties.Name) { $sessions = [int]$script:health.sessions }
    return Get-YouJPPanelState -Installed $script:installed -Checked $script:healthChecked `
        -Owned $owned -SettingUp $settingUp -Stopping ([bool]$script:stopRequestedAt) `
        -Ready $ready -Conflict ([bool]$script:health -and -not $ready) -Sessions $sessions -Failure $script:failure
}

function Get-TranslationName([string]$Provider) {
    switch -Regex ($Provider) {
        '^(llm|ollama)' { return 'Ollama local' }
        '^nllb' { return 'NLLB local' }
        '^none$' { return 'Solo japonés' }
        default { return 'Por iniciar' }
    }
}

function Update-Panel {
    $view = Get-PanelState
    $ui.StatusLabel.Text = $view.Label
    $ui.SidebarStatus.Text = $view.Label
    $ui.StatusTitle.Text = $view.Title
    $ui.StatusDetail.Text = $view.Detail
    $ui.ActivityStatus.Text = $view.Label
    $ui.ActivityDetail.Text = $view.Detail
    $ui.PrimaryAction.Content = $view.Primary
    $ui.PrimaryAction.IsEnabled = $view.CanAct
    $ui.StopButton.Visibility = if ($view.CanStop -or $view.Kind -eq 'stopping') { 'Visible' } else { 'Collapsed' }
    $ui.StopButton.IsEnabled = $view.CanStop
    $ui.BusyProgress.Visibility = if ($view.Busy) { 'Visible' } else { 'Collapsed' }
    $ui.InstallButton.IsEnabled = $view.CanSetup
    $ui.DeviceChoice.IsEnabled = $view.CanSetup
    $ui.TranslationChoice.IsEnabled = $view.CanSetup
    $ui.InstallButton.Content = if ($view.Kind -eq 'setup') { 'Preparando…' } else { 'Preparar / actualizar' }
    $ui.SetupHint.Text = if ($view.Kind -eq 'setup') { 'La preparación sigue en marcha. Consulta Actividad para ver el progreso.' }
        elseif (-not $view.CanSetup) { 'Detén YouJP antes de cambiar o actualizar la configuración.' }
        elseif ($script:installed) { 'Tu equipo está preparado. Actualiza solo si cambias estas opciones o la versión de YouJP.' }
        else { 'Cuando termine la preparación, vuelve a Tu sesión para iniciar YouJP.' }
    $colors = switch ($view.Tone) {
        'green' { @('#416A43', '#E4EBD9') }
        'red' { @('#A3482D', '#F4E3D4') }
        'blue' { @('#986435', '#F1E5CD') }
        default { @('#68745F', '#E6E8DD') }
    }
    $brush = [Windows.Media.BrushConverter]::new()
    $ui.StatusDot.Fill = $brush.ConvertFromString($colors[0])
    $ui.SidebarDot.Fill = $brush.ConvertFromString($colors[0])
    $ui.StatusLabel.Foreground = $brush.ConvertFromString($colors[0])
    $ui.StatusPill.Background = $brush.ConvertFromString($colors[1])
    $model = 'Por iniciar'; $device = [string]$script:runtime.asr_device; $provider = [string]$script:runtime.mt_provider
    if (Test-YouJPHealth $script:health) {
        $model = [string]$script:health.asr_model; $device = [string]$script:health.device; $provider = [string]$script:health.mt_provider
    } elseif (($Preview -or $SmokeTest) -and $view.Kind -in @('ready', 'capturing')) {
        $model = 'large-v3-turbo'; $device = 'cuda'; $provider = 'nllb'
    }
    $ui.ModelValue.Text = $model
    $ui.DeviceValue.Text = switch ($device) { 'cuda' { 'GPU NVIDIA' } 'cpu' { 'CPU' } default { 'Automático' } }
    $ui.TranslationValue.Text = Get-TranslationName $provider
    if ($view.Kind -in @('ready', 'capturing') -and -not $view.CanStop) {
        $ui.ActivityDetail.Text += ' El motor se inició fuera de esta ventana; detenlo desde su aplicación de origen.'
    }
    if ($tray) { $tray.Text = 'YouJP - ' + $view.Label }
}

function Set-Failure([string]$Message) {
    $script:failure = $Message
    Update-Panel
    $ui.ActivityDetail.Text = $Message
}

function Update-Log {
    if ($Preview) {
        $ui.LogText.Text = "Vista previa del registro`r`n`r`nAquí aparecerán el progreso de la preparación y los mensajes de tu sesión."
        return
    }
    if (-not $script:logPath -or -not (Test-Path -LiteralPath $script:logPath)) {
        $ui.LogText.Text = "Todavía no hay actividad.`r`n`r`nInicia YouJP o prepara tu equipo para ver el progreso aquí."
        $ui.CopyLogsButton.IsEnabled = $false
        return
    }
    # Las consultas de salud correctas saturan la interfaz; quedan en los registros.
    $lines = @(Get-Content -LiteralPath $script:logPath -Tail 400 -Encoding UTF8 |
        Where-Object { $_ -notmatch '"GET /health HTTP/[^\"]+" 200 OK' } | Select-Object -Last 100)
    if ($script:errorLogPath -and (Test-Path -LiteralPath $script:errorLogPath)) {
        $errors = @(Get-Content -LiteralPath $script:errorLogPath -Tail 60 -Encoding UTF8)
        if ($errors.Count) { $lines += @('', '--- Diagnóstico ---') + $errors }
    }
    $content = $lines -join [Environment]::NewLine
    if (-not $content) { $content = 'No hay mensajes nuevos en el registro reciente. Puedes consultar los registros completos en su carpeta.' }
    if ($ui.LogText.Text -ne $content) {
        $atEnd = $ui.LogText.VerticalOffset -ge $ui.LogText.ExtentHeight - $ui.LogText.ViewportHeight - 4
        $ui.LogText.Text = $content
        if ($atEnd) { $ui.LogText.ScrollToEnd() }
        $ui.CopyFeedback.Text = ''
    }
    $ui.CopyLogsButton.IsEnabled = $true
}

function Start-Setup {
    if ($Preview) { $script:previewKind = 'setup'; Update-Panel; Show-Page 'activity'; return }
    if (-not (Get-PanelState).CanSetup) { return }
    try {
        New-Item -ItemType Directory -Force -Path $script:RuntimeDir | Out-Null
        $stamp = [Guid]::NewGuid().ToString('N')
        $script:logPath = Join-Path $script:RuntimeDir "setup-$stamp.log"
        $script:errorLogPath = Join-Path $script:RuntimeDir "setup-$stamp.err.log"
        $selectedDevice = @('Auto', 'cuda', 'cpu')[$ui.DeviceChoice.SelectedIndex]
        $selectedMt = @('Auto', 'llm', 'nllb', 'none')[$ui.TranslationChoice.SelectedIndex]
        $setupPath = Join-Path $PSScriptRoot 'Setup.ps1'
        $script:setupProcess = Start-Process -FilePath $script:PowerShellExe -WindowStyle Hidden -PassThru `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $setupPath),
                '-Device', $selectedDevice, '-Translation', $selectedMt) `
            -RedirectStandardOutput $script:logPath -RedirectStandardError $script:errorLogPath
        $preferences = @{ device = $ui.DeviceChoice.SelectedIndex; translation = $ui.TranslationChoice.SelectedIndex } | ConvertTo-Json
        [IO.File]::WriteAllText((Join-Path $script:RuntimeDir 'ui-preferences.json'), $preferences)
        $script:failure = ''
        Update-Panel
        Show-Page 'activity'
    } catch { Set-Failure $_.Exception.Message }
}

function Start-Backend {
    if ($Preview) { $script:previewKind = 'ready'; Update-Panel; return }
    try {
        $script:runtime = Get-YouJPRuntime
        if (-not (Test-Installation)) { throw 'Prepara o actualiza tu equipo desde Configuración antes de iniciar.' }
        $listener = Get-NetTCPConnection -LocalPort $script:runtime.port -State Listen -ErrorAction SilentlyContinue
        if ($listener) { throw "El puerto $($script:runtime.port) ya está ocupado. Espera a que termine la comprobación o revisa Actividad." }
        $stamp = [Guid]::NewGuid().ToString('N')
        $script:stopFile = Join-Path $script:RuntimeDir "stop-$stamp"
        $script:logPath = Join-Path $script:RuntimeDir "backend-$stamp.log"
        $script:errorLogPath = Join-Path $script:RuntimeDir "backend-$stamp.err.log"
        $env:PYTHONUTF8 = '1'
        $python = Join-Path $script:ProjectRoot 'backend/.venv/Scripts/python.exe'
        $script:backendProcess = Start-Process -FilePath $python -WindowStyle Hidden -PassThru `
            -WorkingDirectory (Join-Path $script:ProjectRoot 'backend') `
            -ArgumentList @('-u', '-m', 'youjp.launcher', '--stop-file', ('"{0}"' -f $script:stopFile)) `
            -RedirectStandardOutput $script:logPath -RedirectStandardError $script:errorLogPath
        $script:failure = ''
        Update-Panel
    } catch { Set-Failure $_.Exception.Message }
}

function Stop-Backend {
    if ($Preview) { $script:previewKind = 'idle'; Update-Panel; return }
    if ($script:backendProcess -and -not $script:backendProcess.HasExited -and -not $script:stopRequestedAt) {
        [IO.File]::WriteAllText($script:stopFile, 'stop')
        $script:stopRequestedAt = [DateTime]::UtcNow
        Update-Panel
    }
}

function Open-LocalFolder([string]$Folder) {
    try {
        if (-not (Test-Path -LiteralPath $Folder)) { throw 'Esta carpeta aún no existe. Prepara tu equipo desde Configuración.' }
        Start-Process -FilePath 'explorer.exe' -ArgumentList ('"{0}"' -f $Folder) -WindowStyle Normal
    } catch { Set-Failure $_.Exception.Message; Show-Page 'activity' }
}

$ui.NavHome.Add_Checked({ Show-Page 'home' })
$ui.NavSettings.Add_Checked({ Show-Page 'settings' })
$ui.NavActivity.Add_Checked({ Show-Page 'activity' })
$ui.PrimaryAction.Add_Click({
    switch ((Get-PanelState).Action) {
        'start' { Start-Backend }
        'settings' { Show-Page 'settings' }
        'activity' { Show-Page 'activity' }
        'youtube' { if (-not $Preview) { try { Start-Process 'https://www.youtube.com/' } catch { Set-Failure $_.Exception.Message } } }
    }
})
$ui.StopButton.Add_Click({ try { Stop-Backend } catch { Set-Failure $_.Exception.Message } })
$ui.InstallButton.Add_Click({ Start-Setup })
$ui.SetupActivityButton.Add_Click({ Show-Page 'activity' })
$ui.ExtensionFolder.Add_Click({ Open-LocalFolder (Join-Path $script:ProjectRoot 'extension/.output/chrome-mv3') })
$ui.OpenLogsButton.Add_Click({ Open-LocalFolder $script:RuntimeDir })
$ui.CopyLogsButton.Add_Click({
    try { [Windows.Clipboard]::SetText($ui.LogText.Text); $ui.CopyFeedback.Text = 'Copiado' }
    catch { $ui.CopyFeedback.Text = 'No se pudo copiar. Inténtalo de nuevo.' }
})

$preferencePath = Join-Path $script:RuntimeDir 'ui-preferences.json'
if (Test-Path -LiteralPath $preferencePath) {
    try {
        $preferences = Get-Content -LiteralPath $preferencePath -Raw | ConvertFrom-Json
        if ($preferences.device -in 0..2) { $ui.DeviceChoice.SelectedIndex = [int]$preferences.device }
        if ($preferences.translation -in 0..3) { $ui.TranslationChoice.SelectedIndex = [int]$preferences.translation }
    } catch { <# Las preferencias incompletas no impiden iniciar. #> }
}
if (Test-Path -LiteralPath $script:RuntimeDir) {
    $latestLog = Get-ChildItem -LiteralPath $script:RuntimeDir -Filter '*.log' |
        Where-Object { $_.Name -match '^(setup|backend)-[a-f0-9]+\.log$' } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestLog) {
        $script:logPath = $latestLog.FullName
        $script:errorLogPath = [IO.Path]::ChangeExtension($script:logPath, '.err.log')
    }
}

$tray = $null
$trayMenu = $null
$application = $null
if (-not $SmokeTest) {
    $application = [Windows.Application]::new()
    $application.ShutdownMode = if ($Preview) { 'OnMainWindowClose' } else { 'OnExplicitShutdown' }
    if (-not $Preview) {
        $tray = [Windows.Forms.NotifyIcon]::new()
        $tray.Icon = [Drawing.SystemIcons]::Application
        $appIcon = Join-Path $PSScriptRoot 'assets/youjp.ico'
        if (Test-Path -LiteralPath $appIcon) { $tray.Icon = [Drawing.Icon]::new($appIcon) }
        $tray.Text = 'YouJP'; $tray.Visible = $true
        $trayMenu = [Windows.Forms.ContextMenuStrip]::new()
        $null = $trayMenu.Items.Add('Abrir YouJP', $null, { $window.Show(); $window.WindowState = 'Normal'; $window.Activate() | Out-Null })
        $null = $trayMenu.Items.Add('Salir y detener', $null, {
            if ($script:setupProcess -and -not $script:setupProcess.HasExited) {
                $window.Show(); Show-Page 'activity'
                $ui.ActivityDetail.Text = 'Espera a que termine la preparación antes de salir.'
                return
            }
            $script:exitRequested = $true
            Stop-Backend
            if (-not $script:backendProcess -or $script:backendProcess.HasExited) { $application.Shutdown() }
        })
        $tray.ContextMenuStrip = $trayMenu
        $tray.Add_DoubleClick({ $window.Show(); $window.WindowState = 'Normal'; $window.Activate() | Out-Null })
    }
    $window.Add_Closing({
        param($sender, $eventArgs)
        if ($Preview) { return }
        if (-not $script:exitRequested) { $eventArgs.Cancel = $true; $window.Hide() }
    })
}

$timer = [Windows.Threading.DispatcherTimer]::new()
$timer.Interval = [TimeSpan]::FromSeconds(1)
$timer.Add_Tick({
    try {
        if ($script:setupProcess -and $script:setupProcess.HasExited) {
            if ($script:setupProcess.ExitCode -ne 0) { $script:failure = 'La preparación no se completó. Revisa el registro y vuelve a intentarlo desde Configuración.' }
            $script:setupProcess.Dispose(); $script:setupProcess = $null
            $script:installed = Test-Installation
            $script:runtime = Get-YouJPRuntime
        }
        if ($script:backendProcess -and $script:backendProcess.HasExited) {
            if ($script:backendProcess.ExitCode -ne 0) { $script:failure = 'YouJP se detuvo con un error. Revisa el registro para conocer el motivo.' }
            $script:backendProcess.Dispose(); $script:backendProcess = $null
            $script:stopRequestedAt = $null; $script:health = $null
        }
        if ($script:backendProcess -and $script:stopRequestedAt -and ([DateTime]::UtcNow - $script:stopRequestedAt).TotalSeconds -gt 20) {
            # Solo el proceso iniciado por este panel; nunca terminar todos los Python.
            if (-not $script:backendProcess.HasExited) { $script:backendProcess.Kill() }
        }
        if ($script:healthTask -and $script:healthTask.IsCompleted) {
            $script:health = $null
            try { $script:health = $script:healthTask.GetAwaiter().GetResult() | ConvertFrom-Json } catch {}
            $script:healthTask = $null; $script:healthChecked = $true
            if (Test-YouJPHealth $script:health) { $script:failure = '' }
        }
        if (-not $script:healthTask) {
            $script:healthTask = $script:http.GetStringAsync("http://127.0.0.1:$($script:runtime.port)/health")
        }
        Update-Panel
        if ($script:page -eq 'activity') { Update-Log }
        if ($script:exitRequested -and -not $script:backendProcess) { $application.Shutdown() }
    } catch { Set-Failure $_.Exception.Message }
})

try {
    Update-Panel
    Update-Log
    if ($SmokeTest) {
        foreach ($name in @('PrimaryAction', 'StopButton', 'InstallButton', 'DeviceChoice', 'TranslationChoice', 'LogText', 'StatusTitle')) {
            if (-not $ui.ContainsKey($name)) { throw "Falta el control $name." }
        }
        foreach ($kind in @('idle', 'ready', 'capturing', 'starting', 'setup', 'error', 'unprepared')) {
            $script:previewKind = $kind
            Update-Panel
            if (-not $ui.StatusTitle.Text) { throw "Estado sin título: $kind" }
        }
        foreach ($page in @('home', 'settings', 'activity')) {
            Show-Page $page
            $window.Measure([Windows.Size]::new(1100, 800))
            $window.Arrange([Windows.Rect]::new(0, 0, 1100, 800))
            $window.UpdateLayout()
        }
        Write-Output "Panel WPF OK: $($ui.Count) controles, 7 estados y 3 pantallas, versión $script:appVersion"
    } else {
        if (-not $Preview) { $timer.Start() }
        $null = $application.Run($window)
    }
} finally {
    $timer.Stop()
    if ($tray) { $tray.Visible = $false; $tray.Icon.Dispose(); $tray.Dispose() }
    if ($trayMenu) { $trayMenu.Dispose() }
    $script:http.Dispose()
    if ($mutex) { $mutex.ReleaseMutex(); $mutex.Dispose() }
}
