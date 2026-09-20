param([switch]$SmokeTest)
. (Join-Path $PSScriptRoot 'Common.ps1')
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Net.Http
[Windows.Forms.Application]::EnableVisualStyles()

# Only one panel per checkout. A second checkout has independent ownership.
$hash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash(
    [Text.Encoding]::UTF8.GetBytes($script:ProjectRoot.ToLowerInvariant()))).Replace('-', '').Substring(0, 20)
$mutex = [Threading.Mutex]::new($false, "Local\YouJP-$hash")
if (-not $mutex.WaitOne(0)) {
    if (-not $SmokeTest) { [Windows.Forms.MessageBox]::Show('YouJP ya esta abierto. Busca su icono en la bandeja.', 'YouJP') | Out-Null }
    $mutex.Dispose()
    exit 0
}

$script:backendProcess = $null
$script:setupProcess = $null
$script:stopFile = $null
$script:stopRequestedAt = $null
$script:exitRequested = $false
$script:healthTask = $null
$script:health = $null
$script:logPath = $null
$script:errorLogPath = $null
$script:http = [Net.Http.HttpClient]::new()
$script:http.Timeout = [TimeSpan]::FromSeconds(2)

$form = [Windows.Forms.Form]::new()
$form.Text = 'YouJP ' + (Get-YouJPVersion)
$form.ClientSize = [Drawing.Size]::new(740, 570)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox = $false
$form.Font = [Drawing.Font]::new('Segoe UI', 10)

function Add-Label([string]$Text, [int]$X, [int]$Y, [int]$Width, [int]$Height) {
    $control = [Windows.Forms.Label]::new()
    $control.Text = $Text
    $control.SetBounds($X, $Y, $Width, $Height)
    $form.Controls.Add($control)
    return $control
}
function Add-Button([string]$Text, [int]$X, [int]$Y, [int]$Width, [scriptblock]$Action) {
    $control = [Windows.Forms.Button]::new()
    $control.Text = $Text
    $control.SetBounds($X, $Y, $Width, 36)
    $control.Add_Click($Action)
    $form.Controls.Add($control)
    return $control
}

$heading = Add-Label 'Subtitulos japoneses, en tu equipo' 24 20 690 36
$heading.Font = [Drawing.Font]::new('Segoe UI', 17, [Drawing.FontStyle]::Bold)
$status = Add-Label 'Comprobando el backend...' 24 65 690 44
$status.ForeColor = [Drawing.Color]::FromArgb(36, 66, 124)
$null = Add-Label '1. Prepara el equipo (solo la primera vez o al actualizar)' 24 119 690 26
$null = Add-Label 'Procesamiento' 24 155 190 24
$device = [Windows.Forms.ComboBox]::new()
$device.DropDownStyle = 'DropDownList'
$device.SetBounds(24, 181, 220, 28)
$device.Items.AddRange(@('Automatico', 'GPU NVIDIA', 'CPU (mas lento)'))
$device.SelectedIndex = 0
$form.Controls.Add($device)
$null = Add-Label 'Traduccion' 264 155 195 24
$translation = [Windows.Forms.ComboBox]::new()
$translation.DropDownStyle = 'DropDownList'
$translation.SetBounds(264, 181, 230, 28)
$translation.Items.AddRange(@('Automatica', 'Ollama (ya instalado)', 'NLLB local', 'Solo japones'))
$translation.SelectedIndex = 0
$form.Controls.Add($translation)
$null = Add-Label 'Se descargan Python, modelos y diccionarios. Puede ocupar varios GB. Tu archivo .env tiene prioridad sobre estas opciones.' 24 219 690 42

function Start-Setup {
    try {
        New-Item -ItemType Directory -Force -Path $script:RuntimeDir | Out-Null
        $stamp = [Guid]::NewGuid().ToString('N')
        $script:logPath = Join-Path $script:RuntimeDir "setup-$stamp.log"
        $script:errorLogPath = Join-Path $script:RuntimeDir "setup-$stamp.err.log"
        $selectedDevice = @('Auto', 'cuda', 'cpu')[$device.SelectedIndex]
        $selectedMt = @('Auto', 'llm', 'nllb', 'none')[$translation.SelectedIndex]
        $setupPath = Join-Path $PSScriptRoot 'Setup.ps1'
        $script:setupProcess = Start-Process -FilePath $script:PowerShellExe -WindowStyle Hidden -PassThru `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $setupPath),
                '-Device', $selectedDevice, '-Translation', $selectedMt) `
            -RedirectStandardOutput $script:logPath -RedirectStandardError $script:errorLogPath
        $status.Text = 'Instalando. Puedes ver el progreso debajo; las descargas pueden tardar.'
        $install.Enabled = $false
        $start.Enabled = $false
    } catch { $status.Text = $_.Exception.Message }
}

function Start-Backend {
    try {
        $runtime = Get-YouJPRuntime
        $python = Join-Path $script:ProjectRoot 'backend/.venv/Scripts/python.exe'
        $marker = Join-Path $script:RuntimeDir 'installed-version'
        if (-not (Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw).Trim() -ne (Get-YouJPVersion)) {
            throw 'Pulsa Preparar / actualizar antes de iniciar esta version.'
        }
        if (-not (Test-Path -LiteralPath $python)) { throw 'Falta el entorno Python. Pulsa Preparar / actualizar.' }
        $listener = Get-NetTCPConnection -LocalPort $runtime.port -State Listen -ErrorAction SilentlyContinue
        if ($listener) { throw "El puerto $($runtime.port) ya esta ocupado. No se iniciara otro backend." }
        $stamp = [Guid]::NewGuid().ToString('N')
        $script:stopFile = Join-Path $script:RuntimeDir "stop-$stamp"
        $script:logPath = Join-Path $script:RuntimeDir "backend-$stamp.log"
        $script:errorLogPath = Join-Path $script:RuntimeDir "backend-$stamp.err.log"
        $env:PYTHONUTF8 = '1'
        $script:backendProcess = Start-Process -FilePath $python -WindowStyle Hidden -PassThru `
            -WorkingDirectory (Join-Path $script:ProjectRoot 'backend') `
            -ArgumentList @('-u', '-m', 'youjp.launcher', '--stop-file', ('"{0}"' -f $script:stopFile)) `
            -RedirectStandardOutput $script:logPath -RedirectStandardError $script:errorLogPath
        $status.Text = 'Cargando modelos. El primer inicio puede tardar varios minutos...'
        $start.Enabled = $false
        $install.Enabled = $false
    } catch { $status.Text = $_.Exception.Message }
}

function Stop-Backend {
    if ($script:backendProcess -and -not $script:backendProcess.HasExited -and -not $script:stopRequestedAt) {
        [IO.File]::WriteAllText($script:stopFile, 'stop')
        $script:stopRequestedAt = [DateTime]::UtcNow
        $status.Text = 'Deteniendo el backend y liberando los modelos...'
    }
}

$install = Add-Button 'Preparar / actualizar' 515 178 199 { Start-Setup }
$null = Add-Label '2. Inicia YouJP y activa la extension en YouTube' 24 272 690 26
$start = Add-Button 'Iniciar' 24 310 130 { Start-Backend }
$stop = Add-Button 'Detener' 164 310 130 { Stop-Backend }
$stop.Enabled = $false
$null = Add-Button 'Carpeta extension' 304 310 190 {
    $folder = Join-Path $script:ProjectRoot 'extension/.output/chrome-mv3'
    if (Test-Path -LiteralPath $folder) { Start-Process -FilePath 'explorer.exe' -ArgumentList ('"{0}"' -f $folder) -WindowStyle Normal }
    else { $status.Text = 'Primero prepara el equipo para compilar la extension.' }
}
$null = Add-Button 'Ver registros' 504 310 210 {
    if (Test-Path -LiteralPath $script:RuntimeDir) { Start-Process -FilePath 'explorer.exe' -ArgumentList ('"{0}"' -f $script:RuntimeDir) -WindowStyle Normal }
}
$null = Add-Label 'Chrome / Edge: abre chrome://extensions, activa Modo de desarrollador y carga la carpeta de la extension. Tras actualizarla, pulsa Recargar.' 24 357 690 44
$logs = [Windows.Forms.TextBox]::new()
$logs.Multiline = $true
$logs.ReadOnly = $true
$logs.ScrollBars = 'Vertical'
$logs.Font = [Drawing.Font]::new('Consolas', 9)
$logs.SetBounds(24, 410, 690, 136)
$form.Controls.Add($logs)

$tray = [Windows.Forms.NotifyIcon]::new()
$tray.Icon = [Drawing.SystemIcons]::Application
$tray.Text = 'YouJP'
$tray.Visible = -not $SmokeTest
$menu = [Windows.Forms.ContextMenuStrip]::new()
$null = $menu.Items.Add('Abrir YouJP', $null, { $form.Show(); $form.Activate() })
$null = $menu.Items.Add('Salir y detener', $null, {
    if ($script:setupProcess -and -not $script:setupProcess.HasExited) {
        $form.Show()
        $status.Text = 'Espera a que termine la instalacion antes de salir.'
        return
    }
    $script:exitRequested = $true
    Stop-Backend
    if (-not $script:backendProcess -or $script:backendProcess.HasExited) { $form.Close() }
})
$tray.ContextMenuStrip = $menu
$tray.Add_DoubleClick({ $form.Show(); $form.Activate() })
$form.Add_FormClosing({
    param($sender, $eventArgs)
    if (-not $script:exitRequested) { $eventArgs.Cancel = $true; $form.Hide() }
})

$timer = [Windows.Forms.Timer]::new()
$timer.Interval = 1000
$timer.Add_Tick({
    try {
        $settingUp = $script:setupProcess -and -not $script:setupProcess.HasExited
        $owned = $script:backendProcess -and -not $script:backendProcess.HasExited
        if ($script:setupProcess -and $script:setupProcess.HasExited) {
            $status.Text = if ($script:setupProcess.ExitCode -eq 0) { 'Instalacion lista. Pulsa Iniciar.' } else { 'No se completo la instalacion. Revisa los registros y vuelve a intentarlo.' }
            $script:setupProcess.Dispose()
            $script:setupProcess = $null
        }
        if ($script:backendProcess -and $script:backendProcess.HasExited) {
            $status.Text = if ($script:backendProcess.ExitCode -eq 0) { 'Backend detenido.' } else { 'El backend termino con un error. Revisa los registros.' }
            $script:backendProcess.Dispose()
            $script:backendProcess = $null
            $script:stopRequestedAt = $null
        }
        if ($owned -and $script:stopRequestedAt -and ([DateTime]::UtcNow - $script:stopRequestedAt).TotalSeconds -gt 20) {
            # Process object, not a recycled PID or a blanket python kill.
            $script:backendProcess.Kill()
        }
        if ($script:healthTask -and $script:healthTask.IsCompleted) {
            $script:health = $null
            try { $script:health = $script:healthTask.GetAwaiter().GetResult() | ConvertFrom-Json } catch {}
            $script:healthTask = $null
            if (Test-YouJPHealth $script:health) {
                if (-not $script:stopRequestedAt) {
                    $status.Text = "Listo - $($script:health.asr_model) / $($script:health.device) | Traduccion: $($script:health.mt_provider)"
                    if (-not $owned) { $status.Text += ' (iniciado fuera de este panel)' }
                }
            } elseif ($script:health) { $status.Text = 'Hay otro servicio o una version incompatible en el puerto. Revisa los registros.' }
            elseif (-not $owned -and -not $settingUp -and $status.Text -eq 'Comprobando el backend...') { $status.Text = 'Backend detenido. Prepara el equipo o pulsa Iniciar.' }
        }
        if (-not $script:healthTask) {
            $runtime = Get-YouJPRuntime
            $script:healthTask = $script:http.GetStringAsync("http://127.0.0.1:$($runtime.port)/health")
        }
        $install.Enabled = -not $owned -and -not $settingUp -and -not $script:health
        $start.Enabled = $install.Enabled
        $stop.Enabled = $owned -and -not $script:stopRequestedAt
        $device.Enabled = $install.Enabled
        $translation.Enabled = $install.Enabled
        $tray.Text = if (Test-YouJPHealth $script:health) { 'YouJP - listo' } elseif ($settingUp) { 'YouJP - instalando' } elseif ($owned) { 'YouJP - iniciando' } else { 'YouJP - detenido' }
        if ($script:logPath -and (Test-Path -LiteralPath $script:logPath)) {
            $lines = @(Get-Content -LiteralPath $script:logPath -Tail 14 -Encoding UTF8)
            if (Test-Path -LiteralPath $script:errorLogPath) { $lines += @(Get-Content -LiteralPath $script:errorLogPath -Tail 14 -Encoding UTF8) }
            $logs.Text = $lines -join [Environment]::NewLine
        }
        if ($script:exitRequested -and -not $owned) { $form.Close() }
    } catch { $status.Text = $_.Exception.Message }
})

try {
    if ($SmokeTest) {
        if ($form.Controls.Count -lt 15) { throw 'Faltan controles del asistente.' }
        Write-Output "Panel OK: $($form.Controls.Count) controles, version $(Get-YouJPVersion)"
    } else {
        $timer.Start()
        [Windows.Forms.Application]::Run($form)
    }
} finally {
    $timer.Stop()
    $timer.Dispose()
    $tray.Visible = $false
    $tray.Dispose()
    $script:http.Dispose()
    $form.Dispose()
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
