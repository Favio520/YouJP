param(
    [switch]$SmokeTest,
    [switch]$Preview,
    [ValidateSet('idle', 'ready', 'capturing', 'starting', 'setup', 'error', 'unprepared')]
    [string]$PreviewState = 'idle',
    [ValidateSet('es', 'en')][string]$Language = 'es'
)
. (Join-Path $PSScriptRoot 'Common.ps1')
. (Join-Path $PSScriptRoot 'Localization.ps1')
$script:UiLanguage = $Language
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
    try { $ownsMutex = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) {
        [Windows.MessageBox]::Show((Get-YouJPText 'YouJP ya está abierto. Busca su icono en la bandeja del sistema.'), 'YouJP') | Out-Null
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
if (-not ($SmokeTest -or $Preview)) {
    try { $script:runtime = Get-YouJPEffectiveRuntime }
    catch { $script:failure = (Get-YouJPText 'No se pudo leer la configuración actual. Revisa Actividad o prepara el equipo desde Configuración.') }
}

function Test-Installation {
    return Test-YouJPInstallation
}
$script:installed = Test-Installation

if (-not ($SmokeTest -or $Preview)) {
    $savedUi = Join-Path $script:RuntimeDir 'ui-preferences.json'
    if (Test-Path -LiteralPath $savedUi) {
        try { $saved = Get-Content -LiteralPath $savedUi -Raw | ConvertFrom-Json; if ($saved.language -in @('es','en')) { $script:UiLanguage = $saved.language } } catch {}
    }
}

$markup = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'YouJP.xaml'))
$reader = [Xml.XmlNodeReader]::new([xml]$markup)
try { $window = [Windows.Markup.XamlReader]::Load($reader) } finally { $reader.Close() }
$ui = @{}
foreach ($match in [regex]::Matches($markup, 'x:Name="([^"]+)"')) {
    if ($ui.ContainsKey($match.Groups[1].Value)) { throw "Duplicate XAML control: $($match.Groups[1].Value)" }
    $control = $window.FindName($match.Groups[1].Value)
    if ($control) { $ui[$match.Groups[1].Value] = $control }
}
Set-YouJPViewLanguage $window
# WPF Border.ClipToBounds clips a rectangle; clip the artwork to its rounded frame.
$ui.HeroSurface.Add_SizeChanged({
    param($sender, $eventArgs)
    $sender.Clip = [Windows.Media.RectangleGeometry]::new(
        [Windows.Rect]::new(0, 0, $sender.ActualWidth, $sender.ActualHeight), 21, 21)
})
$window.Title = 'YouJP ' + $script:appVersion
$window.Width = [Math]::Min(1180, [Windows.SystemParameters]::WorkArea.Width - 32)
$window.Height = [Math]::Min(850, [Windows.SystemParameters]::WorkArea.Height - 32)
$ui.VersionLabel.Text = 'YouJP  /  ' + $script:appVersion
$iconPath = Join-Path $PSScriptRoot 'assets/app-logo.png'
if (Test-Path -LiteralPath $iconPath) {
    $brandImage = [Windows.Media.Imaging.BitmapImage]::new([Uri]$iconPath)
    $ui.BrandIcon.Source = $brandImage
    $window.Icon = $brandImage
}
$mascotPath = Join-Path $PSScriptRoot 'assets/mascot-pastel.png'
if (Test-Path -LiteralPath $mascotPath) {
    $ui.MascotImage.Source = [Windows.Media.Imaging.BitmapImage]::new([Uri]$mascotPath)
}
$landscapePath = Join-Path $PSScriptRoot 'assets/fuji-pastel.png'
if (Test-Path -LiteralPath $landscapePath) {
    $ui.HeaderLandscape.ImageSource = [Windows.Media.Imaging.BitmapImage]::new([Uri]$landscapePath)
}
if ($Preview) {
    $window.Title += (Get-YouJPText ' — Vista previa')
    $ui.PreviewLabel.Visibility = 'Visible'
    $ui.FooterHint.Text = (Get-YouJPText 'Vista previa del diseño. Los controles no inician descargas ni procesos.')
}

function Show-Page([string]$Page) {
    $script:page = $Page
    $ui.HomePage.Visibility = 'Collapsed'
    $ui.SettingsPage.Visibility = 'Collapsed'
    $ui.ActivityPage.Visibility = 'Collapsed'
    $ui.HistoryPage.Visibility = 'Collapsed'
    switch ($Page) {
        'home' {
            $ui.HomePage.Visibility = 'Visible'; $ui.NavHome.IsChecked = $true
            $ui.PageEyebrow.Text = (Get-YouJPText '今日の日本語  /  TU ESPACIO DE APRENDIZAJE')
            $ui.PageTitle.Text = (Get-YouJPText 'Tu espacio de japonés'); $ui.PageDescription.Text = (Get-YouJPText 'Un poco de japonés. A tu ritmo.')
        }
        'settings' {
            $ui.SettingsPage.Visibility = 'Visible'; $ui.NavSettings.IsChecked = $true
            $ui.PageEyebrow.Text = (Get-YouJPText '準備  /  A TU MANERA')
            $ui.PageTitle.Text = (Get-YouJPText 'Configuración'); $ui.PageDescription.Text = (Get-YouJPText 'Ajusta YouJP para que vaya contigo.')
        }
        'activity' {
            $ui.ActivityPage.Visibility = 'Visible'; $ui.NavActivity.IsChecked = $true
            $ui.PageEyebrow.Text = (Get-YouJPText '記録  /  TODO EN ORDEN')
            $ui.PageTitle.Text = (Get-YouJPText 'Actividad'); $ui.PageDescription.Text = (Get-YouJPText 'Mira qué está haciendo YouJP ahora mismo.')
            Update-Log
        }
        'history' {
            $ui.HistoryPage.Visibility = 'Visible'; $ui.NavHistory.IsChecked = $true
            $ui.PageEyebrow.Text = (Get-YouJPText '履歴  /  LO QUE YA HAS VISTO')
            $ui.PageTitle.Text = (Get-YouJPText 'Historial'); $ui.PageDescription.Text = (Get-YouJPText 'Las páginas que YouJP ha traducido para ti.')
            Update-History
        }
    }
    if (-not $SmokeTest) {
        $pageControl = switch ($Page) { 'home' { $ui.HomePage } 'settings' { $ui.SettingsPage } 'activity' { $ui.ActivityPage } 'history' { $ui.HistoryPage } }
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
            -Failure $(if ($script:previewKind -eq 'error') { (Get-YouJPText 'No se pudo cargar el modelo. Revisa el registro y vuelve a intentarlo.') } else { '' })
    }
    $owned = $script:backendProcess -and -not $script:backendProcess.HasExited
    $settingUp = $script:setupProcess -and -not $script:setupProcess.HasExited
    $ready = Test-YouJPHealth $script:health
    $sessions = 0
    if ($ready -and 'sessions' -in $script:health.PSObject.Properties.Name) {
        $null = [int]::TryParse([string]$script:health.sessions, [ref]$sessions)
        $sessions = [Math]::Max(0, $sessions)
    }
    return Get-YouJPPanelState -Installed $script:installed -Checked $script:healthChecked `
        -Owned $owned -SettingUp $settingUp -Stopping ([bool]$script:stopRequestedAt) `
        -Ready $ready -Conflict ([bool]$script:health -and -not $ready) -Sessions $sessions -Failure $script:failure
}

function Get-TranslationName([string]$Provider) {
    switch -Regex ($Provider) {
        '^(llm|ollama)' { return (Get-YouJPText 'Ollama local') }
        '^nllb' { return (Get-YouJPText 'NLLB local') }
        '^none$' { return (Get-YouJPText 'Solo japonés') }
        default { return (Get-YouJPText 'Por iniciar') }
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
    $ui.InstallButton.Content = if ($view.Kind -eq 'setup') { (Get-YouJPText 'Preparando…') } else { (Get-YouJPText 'Preparar / actualizar') }
    $ui.SetupHint.Text = if ($view.Kind -eq 'setup') { (Get-YouJPText 'La preparación sigue en marcha. Consulta Actividad para ver el progreso.') }
        elseif (-not $view.CanSetup) { (Get-YouJPText 'Detén YouJP antes de cambiar o actualizar la configuración.') }
        elseif ($script:installed) { (Get-YouJPText 'Tu equipo está preparado. Actualiza solo si cambias estas opciones o la versión de YouJP.') }
        else { (Get-YouJPText 'Cuando termine la preparación, vuelve a Tu sesión para iniciar YouJP.') }
    $colors = switch ($view.Tone) {
        'green' { @('#336749', '#EDF7F0', '#83BA99') }
        'red' { @('#AE3B2C', '#FFE8E1', '#FF705E') }
        'blue' { @('#6450A4', '#F1ECFD', '#B9A2F4') }
        default { @('#5C6B7E', '#F1EDE8', '#B9A2F4') }
    }
    $brush = [Windows.Media.BrushConverter]::new()
    $ui.StatusDot.Fill = $brush.ConvertFromString($colors[0])
    $ui.SidebarDot.Fill = $brush.ConvertFromString($colors[2])
    $ui.StatusLabel.Foreground = $brush.ConvertFromString($colors[0])
    $ui.StatusPill.Background = $brush.ConvertFromString($colors[1])
    $ui.StatusPill.BorderBrush = $brush.ConvertFromString($colors[1])
    $needsAttention = $view.Tone -eq 'red'
    $ui.StatusDetailBox.Background = if ($needsAttention) { $brush.ConvertFromString('#FFE8E1') } else { [Windows.Media.Brushes]::Transparent }
    $ui.StatusDetailBox.Padding = if ($needsAttention) { [Windows.Thickness]::new(12) } else { [Windows.Thickness]::new(0) }
    $ui.StatusNoticeIcon.Visibility = if ($needsAttention) { 'Visible' } else { 'Collapsed' }
    $ui.StatusDetail.Foreground = $brush.ConvertFromString($(if ($needsAttention) { '#AE3B2C' } else { '#5C6B7E' }))
    $ui.HomeActivityNotice.Background = $brush.ConvertFromString($colors[1])
    $ui.HomeActivityStatus.Foreground = $brush.ConvertFromString($colors[0])
    $ui.ActivitySummary.Background = $brush.ConvertFromString($colors[1])
    $ui.ActivitySummary.BorderBrush = $brush.ConvertFromString($colors[1])
    $model = (Get-YouJPText 'Por iniciar'); $device = [string]$script:runtime.asr_device; $provider = [string]$script:runtime.mt_provider
    if (Test-YouJPHealth $script:health) {
        $fields = @($script:health.PSObject.Properties.Name)
        if ('asr_model' -in $fields) { $model = [string]$script:health.asr_model }
        if ('device' -in $fields) { $device = [string]$script:health.device }
        if ('mt_provider' -in $fields) { $provider = [string]$script:health.mt_provider }
    } elseif (($Preview -or $SmokeTest) -and $view.Kind -in @('ready', 'capturing')) {
        $model = 'large-v3-turbo'; $device = 'cuda'; $provider = 'nllb'
    }
    $ui.ModelValue.Text = $model
    $ui.DeviceValue.Text = switch ($device) { 'cuda' { 'GPU NVIDIA' } 'cpu' { 'CPU' } default { (Get-YouJPText 'Automático') } }
    $ui.TranslationValue.Text = Get-TranslationName $provider
    $sessionCount = 0
    if (($Preview -or $SmokeTest) -and $view.Kind -eq 'capturing') { $sessionCount = 1 }
    elseif ((Test-YouJPHealth $script:health) -and $script:health.PSObject.Properties.Name -contains 'sessions') {
        $null = [int]::TryParse([string]$script:health.sessions, [ref]$sessionCount)
        $sessionCount = [Math]::Max(0, $sessionCount)
    }
    $ui.HomeActivityStatus.Text = $view.Label
    $ui.HomeActivityDetail.Text = switch ($view.Kind) {
        'capturing' { (Get-YouJPText 'Una pestaña está recibiendo subtítulos.') }
        'ready' { (Get-YouJPText 'El motor está listo para tu próximo vídeo.') }
        'idle' { (Get-YouJPText 'YouJP espera a que inicies una sesión.') }
        'unprepared' { (Get-YouJPText 'Prepara tu equipo desde Configuración.') }
        'error' { (Get-YouJPText 'Revisa Actividad para ver qué ocurrió.') }
        'starting' { (Get-YouJPText 'Cargando los modelos en tu equipo.') }
        'setup' { (Get-YouJPText 'Sigue el progreso de la preparación en Actividad.') }
        'stopping' { (Get-YouJPText 'Liberando los recursos de tu equipo.') }
        'conflict' { (Get-YouJPText 'Revisa Actividad para comprobar la conexión.') }
        default { $view.Detail }
    }
    $ui.HomeSessionCount.Text = [string]$sessionCount
    $progress = if ($sessionCount -gt 0) { 2 } elseif ($view.Kind -in @('ready', 'capturing')) { 1 } else { 0 }
    $ui.SessionProgress.Text = Get-YouJPText "$progress de 2 pasos"
    $ui.SessionProgressBar.Value = $progress
    if ($view.Kind -in @('ready', 'capturing') -and -not $view.CanStop) {
        $ui.ActivityDetail.Text += (Get-YouJPText ' El motor se inició fuera de esta ventana; detenlo desde su aplicación de origen.')
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
        $ui.LogText.Text = (Get-YouJPText "Todavía no hay actividad.`r`n`r`nInicia YouJP o prepara tu equipo para ver el progreso aquí.")
        $ui.CopyLogsButton.IsEnabled = $false
        return
    }
    # Las consultas de salud correctas saturan la interfaz; quedan en los registros.
    $lines = @(Get-Content -LiteralPath $script:logPath -Tail 400 -Encoding UTF8 |
        Where-Object { $_ -notmatch '"GET /health HTTP/[^\"]+" 200 OK' } | Select-Object -Last 100)
    if ($script:errorLogPath -and (Test-Path -LiteralPath $script:errorLogPath)) {
        $errors = @(Get-Content -LiteralPath $script:errorLogPath -Tail 60 -Encoding UTF8)
        if ($errors.Count) { $lines += @('', (Get-YouJPText '--- Diagnóstico ---')) + $errors }
    }
    $content = $lines -join [Environment]::NewLine
    if (-not $content) { $content = (Get-YouJPText 'No hay mensajes nuevos en el registro reciente. Puedes consultar los registros completos en su carpeta.') }
    if ($ui.LogText.Text -ne $content) {
        $atEnd = $ui.LogText.VerticalOffset -ge $ui.LogText.ExtentHeight - $ui.LogText.ViewportHeight - 4
        $ui.LogText.Text = $content
        if ($atEnd) { $ui.LogText.ScrollToEnd() }
        $ui.CopyFeedback.Text = ''
    }
    $ui.CopyLogsButton.IsEnabled = $true
}

function Update-History {
    $selectedPath = if ($ui.HistoryList.SelectedItem) { $ui.HistoryList.SelectedItem.Tag.Path } else { $null }
    $ui.HistoryList.Items.Clear()
    $sessions = @(Get-YouJPHistorySessions)
    foreach ($session in $sessions) {
        $name = if ($session.VideoId) { (Get-YouJPText 'Vídeo') + ' ' + $session.VideoId } else { (Get-YouJPText 'Página sin identificar') }
        $when = if ($session.StartedAt -gt [DateTime]::MinValue) { $session.StartedAt.ToString('yyyy-MM-dd HH:mm') } else { '' }
        $preview = if ($session.Preview.Length -gt 36) { $session.Preview.Substring(0, 36) + '…' } else { $session.Preview }
        $item = [Windows.Controls.ListBoxItem]::new()
        $item.Tag = $session
        $item.Padding = [Windows.Thickness]::new(10, 8, 10, 8)
        $text = [Windows.Controls.TextBlock]::new()
        $text.TextWrapping = 'Wrap'
        $title = [Windows.Documents.Run]::new($name); $title.FontWeight = 'SemiBold'
        $text.Inlines.Add($title)
        $text.Inlines.Add([Windows.Documents.Run]::new("`n$when  ·  " + (Get-YouJPText "$($session.Count) frases")))
        $text.Inlines.Add([Windows.Documents.Run]::new("`n$preview"))
        $item.Content = $text
        $null = $ui.HistoryList.Items.Add($item)
        if ($session.Path -eq $selectedPath) { $ui.HistoryList.SelectedItem = $item }
    }
    $ui.HistoryEmpty.Visibility = if ($sessions.Count) { 'Collapsed' } else { 'Visible' }
    if (-not $ui.HistoryList.SelectedItem -and $sessions.Count) { $ui.HistoryList.SelectedIndex = 0 }
    if (-not $sessions.Count) { Show-HistorySession $null }
}

function Show-HistorySession($Session) {
    $ui.HistoryFeedback.Text = ''
    if (-not $Session) {
        $ui.HistoryTitle.Text = ''; $ui.HistoryMeta.Text = ''; $ui.HistoryText.Text = ''
        $ui.OpenVideoButton.IsEnabled = $false; $ui.CopyHistoryButton.IsEnabled = $false
        return
    }
    try { $data = Read-YouJPHistoryFile $Session.Path } catch { $data = $null }
    if (-not $data) { $ui.HistoryText.Text = (Get-YouJPText 'No se pudo leer este historial.'); return }
    $ui.HistoryTitle.Text = if ($Session.VideoId) { (Get-YouJPText 'Vídeo') + ' ' + $Session.VideoId } else { (Get-YouJPText 'Página sin identificar') }
    $ui.HistoryMeta.Text = $(if ($Session.Url) { $Session.Url } else { $Session.StartedAt.ToString('yyyy-MM-dd HH:mm') })
    $ui.HistoryText.Text = Format-YouJPHistorySession $data
    $ui.OpenVideoButton.IsEnabled = [bool](Get-YouJPHistoryVideoUrl $Session.Url)
    $ui.CopyHistoryButton.IsEnabled = $true
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
        $preferences = @{ device = $ui.DeviceChoice.SelectedIndex; translation = $ui.TranslationChoice.SelectedIndex; language = $script:UiLanguage } | ConvertTo-Json
        [IO.File]::WriteAllText((Join-Path $script:RuntimeDir 'ui-preferences.json'), $preferences)
        $script:failure = ''
        Update-Panel
        Show-Page 'activity'
    } catch { Set-Failure $_.Exception.Message }
}

function Start-Backend {
    if ($Preview) { $script:previewKind = 'ready'; Update-Panel; return }
    $view = Get-PanelState
    if (-not $script:healthChecked -or -not $view.CanAct -or $view.Action -ne 'start') { return }
    try {
        $script:runtime = Get-YouJPEffectiveRuntime
        if (-not (Test-Installation)) { throw (Get-YouJPText 'Prepara o actualiza tu equipo desde Configuración antes de iniciar.') }
        $listener = Get-NetTCPConnection -LocalPort $script:runtime.port -State Listen -ErrorAction SilentlyContinue
        if ($listener) { throw (Get-YouJPText "El puerto $($script:runtime.port) ya está ocupado. Espera a que termine la comprobación o revisa Actividad.") }
        $script:http.CancelPendingRequests()
        $script:healthTask = $null; $script:health = $null; $script:healthChecked = $false
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
        if (-not (Test-Path -LiteralPath $Folder)) { throw (Get-YouJPText 'Esta carpeta aún no existe. Prepara tu equipo desde Configuración.') }
        Start-Process -FilePath 'explorer.exe' -ArgumentList ('"{0}"' -f $Folder) -WindowStyle Normal
    } catch { Set-Failure $_.Exception.Message; Show-Page 'activity' }
}

$ui.UiLanguageChoice.SelectedIndex = if ($script:UiLanguage -eq 'en') { 1 } else { 0 }
$ui.UiLanguageChoice.Add_SelectionChanged({
    $script:UiLanguage = if ($ui.UiLanguageChoice.SelectedIndex -eq 1) { 'en' } else { 'es' }
    Set-YouJPViewLanguage $window
    Show-Page $script:page
    Update-Panel
    if ($trayMenu) {
        $trayMenu.Items[0].Text = Get-YouJPText 'Abrir YouJP'
        $trayMenu.Items[1].Text = Get-YouJPText 'Salir y detener'
    }
    if (-not ($Preview -or $SmokeTest)) {
        New-Item -ItemType Directory -Force -Path $script:RuntimeDir | Out-Null
        $prefs = @{ device = $ui.DeviceChoice.SelectedIndex; translation = $ui.TranslationChoice.SelectedIndex; language = $script:UiLanguage }
        [IO.File]::WriteAllText((Join-Path $script:RuntimeDir 'ui-preferences.json'), ($prefs | ConvertTo-Json))
    }
})

$ui.NavHome.Add_Checked({ Show-Page 'home' })
$ui.NavSettings.Add_Checked({ Show-Page 'settings' })
$ui.NavActivity.Add_Checked({ Show-Page 'activity' })
$ui.NavHistory.Add_Checked({ Show-Page 'history' })
$ui.HistoryList.Add_SelectionChanged({
    if ($ui.HistoryList.SelectedItem) { Show-HistorySession $ui.HistoryList.SelectedItem.Tag }
})
$ui.RefreshHistoryButton.Add_Click({ Update-History })
$ui.OpenHistoryFolderButton.Add_Click({
    $dir = Get-YouJPHistoryDir
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Open-LocalFolder $dir
})
$ui.OpenVideoButton.Add_Click({
    $item = $ui.HistoryList.SelectedItem
    $url = if ($item) { Get-YouJPHistoryVideoUrl $item.Tag.Url } else { $null }
    if ($url -and -not $Preview) { try { Start-Process $url } catch { $ui.HistoryFeedback.Text = $_.Exception.Message } }
})
$ui.CopyHistoryButton.Add_Click({
    try { [Windows.Clipboard]::SetText($ui.HistoryText.Text); $ui.HistoryFeedback.Text = (Get-YouJPText 'Copiado') }
    catch { $ui.HistoryFeedback.Text = (Get-YouJPText 'No se pudo copiar. Inténtalo de nuevo.') }
})
$ui.ViewActivityButton.Add_Click({ Show-Page 'activity' })
$ui.GuideButton.Add_Click({ Show-Page 'home'; $ui.GuideSection.BringIntoView() })
$ui.ResourcesButton.Add_Click({ Show-Page 'home'; $ui.GuideExpander.IsExpanded = $true; $ui.GuideSection.BringIntoView() })
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
    try { [Windows.Clipboard]::SetText($ui.LogText.Text); $ui.CopyFeedback.Text = (Get-YouJPText 'Copiado') }
    catch { $ui.CopyFeedback.Text = (Get-YouJPText 'No se pudo copiar. Inténtalo de nuevo.') }
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
        $appIcon = Join-Path $PSScriptRoot 'assets/youjp-logo.ico'
        if (Test-Path -LiteralPath $appIcon) { $tray.Icon = [Drawing.Icon]::new($appIcon) }
        $tray.Text = 'YouJP'; $tray.Visible = $true
        $trayMenu = [Windows.Forms.ContextMenuStrip]::new()
        $null = $trayMenu.Items.Add((Get-YouJPText 'Abrir YouJP'), $null, { $window.Show(); $window.WindowState = 'Normal'; $window.Activate() | Out-Null })
        $null = $trayMenu.Items.Add((Get-YouJPText 'Salir y detener'), $null, {
            if ($script:setupProcess -and -not $script:setupProcess.HasExited) {
                $window.Show(); Show-Page 'activity'
                $ui.ActivityDetail.Text = (Get-YouJPText 'Espera a que termine la preparación antes de salir.')
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
            if ($script:setupProcess.ExitCode -ne 0) { $script:failure = (Get-YouJPText 'La preparación no se completó. Revisa el registro y vuelve a intentarlo desde Configuración.') }
            $script:setupProcess.Dispose(); $script:setupProcess = $null
            $script:installed = Test-Installation
            $script:runtime = Get-YouJPEffectiveRuntime
            $script:http.CancelPendingRequests()
            $script:healthTask = $null; $script:health = $null; $script:healthChecked = $false
        }
        if ($script:backendProcess -and $script:backendProcess.HasExited) {
            if ($script:backendProcess.ExitCode -ne 0) { $script:failure = (Get-YouJPText 'YouJP se detuvo con un error. Revisa el registro para conocer el motivo.') }
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
        foreach ($page in @('home', 'settings', 'activity', 'history')) {
            Show-Page $page
            $window.Measure([Windows.Size]::new(1100, 800))
            $window.Arrange([Windows.Rect]::new(0, 0, 1100, 800))
            $window.UpdateLayout()
        }
        # Switching languages must update both static controls and live state.
        $ui.UiLanguageChoice.SelectedIndex = 1
        Show-Page 'settings'
        if ($ui.PageTitle.Text -ne 'Settings') { throw 'English settings page did not update.' }
        $script:previewKind = 'ready'; Update-Panel
        if ($ui.StatusLabel.Text -ne 'Ready') { throw 'English engine state did not update.' }
        Set-YouJPViewLanguage $window
        Show-Page 'settings'; Update-Panel
        if ($ui.UiLanguageChoice.SelectedIndex -ne 1 -or $ui.PageTitle.Text -ne 'Settings') { throw 'Refreshing labels reset the language selection.' }
        $ui.UiLanguageChoice.SelectedIndex = 0
        Show-Page 'settings'
        if ($ui.PageTitle.Text -ne 'Configuración') { throw 'Spanish settings page did not restore.' }
        Update-Panel
        if ($ui.StatusLabel.Text -ne 'Listo') { throw 'Spanish engine state did not restore.' }
        Write-Output "Panel WPF OK: $($ui.Count) controles, 7 estados y 4 pantallas, versión $script:appVersion"
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
