<# Offline smoke/decision tests: no downloads, installations or backend launches. #>
. (Join-Path $PSScriptRoot 'Common.ps1')
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

foreach ($file in (Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1')) {
    $tokens = $null
    $parseErrors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors)
    Assert ($parseErrors.Count -eq 0) "Invalid PowerShell syntax: $($file.Name)"
}
Invoke-YouJPCommand -Exe $script:PowerShellExe -Arguments @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-File', (Join-Path $PSScriptRoot 'YouJP.ps1'), '-SmokeTest')
Write-Output 'OK: perfiles de hardware, precedencia, compatibilidad, sintaxis y panel.'
