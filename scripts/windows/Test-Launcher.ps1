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
$health.protocol_version = $schema.'x-youjp'.protocol_version
$health.asr_loaded = 'false'
Assert (-not (Test-YouJPHealth $health)) 'A string must not masquerade as loaded models'

# Load task functions without running setup, diagnostics, or any real command.
$taskTokens = $null
$taskErrors = $null
$taskAst = [Management.Automation.Language.Parser]::ParseFile((Join-Path $script:ProjectRoot 'tasks.ps1'), [ref]$taskTokens, [ref]$taskErrors)
Assert ($taskErrors.Count -eq 0) 'Project tasks must have valid PowerShell syntax'
foreach ($definition in $taskAst.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -like 'Invoke-*' }, $false)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}

# Fixtures never touch the real installation or its saved runtime.
$originalRoot = $script:ProjectRoot
$originalRuntime = $script:RuntimeDir
$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('youjp-launcher-test-' + [Guid]::NewGuid().ToString('N'))
try {
    $script:ProjectRoot = $fixtureRoot
    $script:RuntimeDir = Join-Path $fixtureRoot '.youjp'
    New-Item -ItemType Directory -Path $script:RuntimeDir -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $fixtureRoot 'backend/.venv/Scripts') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $fixtureRoot 'VERSION'), '1.2.3')
    [IO.File]::WriteAllText((Join-Path $fixtureRoot 'backend/.venv/Scripts/python.exe'), '')
    $marker = Join-Path $script:RuntimeDir 'installed-version'
    [IO.File]::WriteAllText($marker, '')
    Assert (-not (Test-YouJPInstallation)) 'Failed setup with an empty marker must remain recoverable'
    [IO.File]::WriteAllText($marker, '1.2.3')
    Assert (Test-YouJPInstallation) 'A matching installation marker should be accepted'
    [IO.File]::WriteAllText($marker, '1.2.2')
    Assert (-not (Test-YouJPInstallation)) 'An outdated marker must require preparation'
    $runtimePath = Join-Path $script:RuntimeDir 'runtime.json'
    foreach ($json in @('', '{', 'null', '[]', '{"port":99999}', '{"port":"oops"}')) {
        [IO.File]::WriteAllText($runtimePath, $json)
        $runtime = Get-YouJPRuntime -WarningAction SilentlyContinue
        Assert ($runtime.port -eq 8770 -and $runtime.asr_device -eq '') 'Invalid runtime data must not crash the panel'
    }
    [IO.File]::WriteAllText($runtimePath, '{"port":9891}')
    $runtime = Get-YouJPRuntime
    Assert ($runtime.port -eq 9891 -and $runtime.mt_provider -eq '') 'Partial runtime config must receive safe defaults'
    & {
        function Invoke-YouJPCommand {
            param([string]$Exe, [string[]]$Arguments)
            Assert ($Arguments[-1] -eq '--print-settings') 'Effective settings must use the read-only mode'
            return '{"port":9991,"app_version":"1.2.3","asr_device":"cpu","mt_provider":"none"}'
        }
        Assert ((Get-YouJPEffectiveRuntime).port -eq 9991) 'Changed environment settings must override the cached runtime port'
        Assert ((Get-YouJPRuntime).port -eq 9891) 'Querying current settings must not rewrite cached configuration'
    }

    & {
        $Root = $fixtureRoot
        $Backend = Join-Path $fixtureRoot 'backend'
        $invocations = [Collections.Generic.List[string]]::new()
        function uv { $invocations.Add(($args -join ' ')); $global:LASTEXITCODE = 23 }
        $failed = $false
        try { Invoke-Setup 6>$null } catch { $failed = $true }
        Assert ($failed -and $invocations.Count -eq 1) 'A failed environment sync must stop setup before model downloads'
        $failed = $false
        try { Invoke-Test } catch { $failed = $true }
        Assert $failed 'A failed test command must fail the task'
    }
    & {
        $Root = $fixtureRoot
        $Backend = Join-Path $fixtureRoot 'backend'
        function Get-Command { return $null }
        function Invoke-Gpu { throw 'Fixture GPU unavailable' }
        $failed = $false
        try { Invoke-Doctor 6>$null } catch { $failed = $_.Exception.Message -eq 'Falta algo de lo marcado arriba.' }
        Assert $failed 'Doctor must report missing dependencies rather than claiming everything is ready'
    }
    $historyDir = Join-Path $script:RuntimeDir 'history'
    New-Item -ItemType Directory -Path $historyDir -Force | Out-Null
    Assert (@(Get-YouJPHistorySessions).Count -eq 0) 'Sin historial no debe haber sesiones'
    $rows = @(
        '{"kind":"session","id":"a1","started_at":"2026-10-03T10:00:00","video_id":"abc","url":"https://www.youtube.com/watch?v=abc","target":"es"}',
        '{"kind":"line","id":1,"start_ms":65000,"ja":"こんにちは"}',
        '{"kind":"tr","id":1,"text":"Hola"}',
        '{"kind":"line","id":2,"start_ms":70000,"ja":"はい"}',
        '{"kind":"line","id":3,"start_ms":7'
    )
    [IO.File]::WriteAllLines((Join-Path $historyDir '20261003-100000-a1.jsonl'), $rows)
    [IO.File]::WriteAllText((Join-Path $historyDir '20261003-090000-empty.jsonl'), '{"kind":"session","id":"b2"}')
    $found = @(Get-YouJPHistorySessions)
    Assert ($found.Count -eq 1 -and $found[0].Count -eq 2 -and $found[0].VideoId -eq 'abc') 'El historial debe ignorar sesiones vacías y líneas a medias'
    $text = Format-YouJPHistorySession (Read-YouJPHistoryFile $found[0].Path)
    Assert ($text -match '\[1:05\] こんにちは' -and $text -match 'Hola') 'La traducción debe aparecer bajo su frase'
    Assert ((Get-YouJPHistoryVideoUrl $found[0].Url) -eq 'https://www.youtube.com/watch?v=abc') 'Un enlace https debe poder abrirse'
    Assert ($null -eq (Get-YouJPHistoryVideoUrl 'file:///C:/Windows/System32/calc.exe')) 'Solo se abren enlaces https'
} finally {
    $script:ProjectRoot = $originalRoot
    $script:RuntimeDir = $originalRuntime
    $resolvedFixture = [IO.Path]::GetFullPath($fixtureRoot)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolvedFixture.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and
        [IO.Path]::GetFileName($resolvedFixture).StartsWith('youjp-launcher-test-')) {
        Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
    }
}

& {
    function nvidia-smi { $global:LASTEXITCODE = 0; 'NVIDIA fixture, 8192, N/A' }
    Assert ($null -eq (Get-YouJPHardware).GPU) 'Unavailable GPU metrics must permit CPU fallback'
}

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
Assert ($view.Title -eq 'El japonés, frase a frase.' -and $view.Detail.Contains('pestaña')) 'Spanish text must retain its accents'
$view = Get-YouJPPanelState -Ready $true -Owned $true -Stopping $true -Checked $true
Assert ($view.Kind -eq 'stopping' -and -not $view.CanStop -and -not $view.CanAct) 'Stopping must override a stale ready response'
$view = Get-YouJPPanelState -SettingUp $true -Checked $true
Assert ($view.Kind -eq 'setup' -and -not $view.CanSetup -and -not $view.CanAct) 'Setup must lock conflicting actions'
$view = Get-YouJPPanelState -Conflict $true -Checked $true
Assert ($view.Action -eq 'activity' -and -not $view.CanSetup) 'An incompatible service must not allow installing over it'
$view = Get-YouJPPanelState -Installed $true -Checked $true -Failure 'Model failed'
Assert ($view.Kind -eq 'error' -and $view.Detail -eq 'Model failed' -and $view.Action -eq 'start') 'Failure details and retry must remain available'

foreach ($file in (Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1')) {
    # Windows PowerShell 5.1 interpreta como ANSI los scripts UTF-8 sin BOM.
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    if ($bytes | Where-Object { $_ -gt 127 }) {
        Assert ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) "UTF-8 BOM requerido: $($file.Name)"
    }
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
