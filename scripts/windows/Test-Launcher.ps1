<# Pruebas aisladas de decisiones: sin descargas, instalación ni backend. #>
. (Join-Path $PSScriptRoot 'Common.ps1')
. (Join-Path $PSScriptRoot 'LauncherState.ps1')
function Assert($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

$noGpu = [pscustomobject]@{ GPU = $null; Ollama = $false }
$cpu = Get-YouJPProfile -Hardware $noGpu
Assert ($cpu.YOUJP_ASR_DEVICE -eq 'cpu') 'No GPU must select CPU'
Assert ($cpu.YOUJP_MT_PROVIDER -eq 'none') 'CPU Auto must avoid two concurrent models'
$gpu = [pscustomobject]@{ GPU = [pscustomobject]@{ Name = 'Test'; TotalMB = 6144; FreeMB = 5500 }; Ollama = $true }
$full = Get-YouJPProfile -Hardware $gpu
Assert ($full.YOUJP_ASR_DEVICE -eq 'cuda' -and $full.YOUJP_MT_PROVIDER -eq 'llm') 'Available GPU/Ollama should be used'
$gpu.Ollama = $false
Assert ((Get-YouJPProfile -Hardware $gpu).YOUJP_MT_PROVIDER -eq 'nllb') 'No Ollama must select a built-in translator'
$gpu.GPU.FreeMB = 1000
Assert ((Get-YouJPProfile -Hardware $gpu).YOUJP_ASR_DEVICE -eq 'cpu') 'Occupied VRAM must select CPU'
Assert ((Get-YouJPProfile -Hardware $gpu -Device cuda -Translation none).YOUJP_ASR_DEVICE -eq 'cuda') 'Explicit GPU choice must win'
$threw = $false
try { $null = Get-YouJPProfile -Hardware $noGpu -Device cuda } catch { $threw = $true }
Assert $threw 'Explicit GPU without NVIDIA should explain the problem'
Assert (-not (Test-YouJPHealth ([pscustomobject]@{ status = 'ok' }))) 'Unrelated HTTP service must not be considered YouJP'
$schema = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'protocol/schema.json') -Raw | ConvertFrom-Json
$health = [pscustomobject]@{ service = 'youjp'; app_version = Get-YouJPVersion;
    protocol_version = $schema.'x-youjp'.protocol_version; asr_loaded = $true }
Assert (Test-YouJPHealth $health) 'Current backend should be ready'
$health.protocol_version = 999
Assert (-not (Test-YouJPHealth $health)) 'Incompatible backend must not be ready'

$view = Get-YouJPPanelState -Installed $true -Checked $false
Assert (-not $view.CanAct -and -not $view.CanSetup) 'First health check must finish before starting or installing'
$view = Get-YouJPPanelState -Installed $false -Checked $true
Assert ($view.Action -eq 'settings' -and $view.CanSetup) 'First run must lead to preparation'
$view = Get-YouJPPanelState -Installed $true -Checked $true
Assert ($view.Action -eq 'start' -and -not $view.CanStop) 'Idle installation can start, not stop'
$view = Get-YouJPPanelState -Installed $true -Checked $true -Owned $true
Assert ($view.Kind -eq 'starting' -and $view.Busy -and $view.CanStop -and -not $view.CanAct) 'Loading models must prevent a duplicate start'
$view = Get-YouJPPanelState -Ready $true -Checked $true
Assert ($view.Kind -eq 'ready' -and $view.Action -eq 'youtube' -and -not $view.CanStop -and -not $view.CanSetup) 'External backend can be used, but not stopped or updated'
$view = Get-YouJPPanelState -Ready $true -Owned $true -Checked $true -Sessions 1
Assert ($view.Kind -eq 'capturing' -and $view.CanStop) 'A live browser connection must differ from backend ready'
$view = Get-YouJPPanelState -Ready $true -Owned $true -Stopping $true -Checked $true
Assert ($view.Kind -eq 'stopping' -and -not $view.CanStop -and -not $view.CanAct) 'Stopping must override a stale ready response'
$view = Get-YouJPPanelState -SettingUp $true -Checked $true
Assert ($view.Kind -eq 'setup' -and -not $view.CanSetup -and -not $view.CanAct) 'Setup must lock conflicting actions'
$view = Get-YouJPPanelState -Conflict $true -Checked $true
Assert ($view.Action -eq 'activity' -and -not $view.CanSetup) 'An incompatible service must not allow installing over it'
$view = Get-YouJPPanelState -Installed $true -Checked $true -Failure 'Model failed'
Assert ($view.Kind -eq 'error' -and $view.Detail -eq 'Model failed' -and $view.Action -eq 'start') 'Failure details and retry must remain available'

foreach ($file in (Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1')) {
    $tokens = $null
    $parseErrors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors)
    Assert ($parseErrors.Count -eq 0) "Invalid PowerShell syntax: $($file.Name)"
}
Invoke-YouJPCommand -Exe $script:PowerShellExe -Arguments @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-File', (Join-Path $PSScriptRoot 'YouJP.ps1'), '-SmokeTest')
$nativeLauncher = Join-Path $script:ProjectRoot 'YouJP.exe'
if (Test-Path -LiteralPath $nativeLauncher) {
    $nativeTest = Start-Process -FilePath $nativeLauncher -ArgumentList '--smoke-test' -WindowStyle Hidden -Wait -PassThru
    Assert ($nativeTest.ExitCode -eq 0) 'Native launcher must load the controller and render all WPF pages'
    $nativeTest.Dispose()
}
Write-Output 'OK: perfiles de hardware, precedencia, compatibilidad, sintaxis y panel.'
