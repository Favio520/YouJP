Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$script:RuntimeDir = Join-Path $script:ProjectRoot '.youjp'
$script:PowerShellExe = Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell/v1.0/powershell.exe'

function Get-YouJPHardware {
    $gpu = $null
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        $rows = & nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits 2>$null
        if ($LASTEXITCODE -eq 0 -and $rows) {
            $parts = (@($rows)[0]) -split ',\s*'
            if ($parts.Count -eq 3) {
                $gpu = [pscustomobject]@{ Name = $parts[0]; TotalMB = [int]$parts[1]; FreeMB = [int]$parts[2] }
            }
        }
    }
    [pscustomobject]@{ GPU = $gpu; Ollama = [bool](Get-Command ollama -ErrorAction SilentlyContinue) }
}

function Get-YouJPProfile {
    param($Hardware, [string]$Device = 'Auto', [string]$Translation = 'Auto')
    $useGpu = $null -ne $Hardware.GPU -and $Hardware.GPU.FreeMB -ge 2000
    if ($Device -eq 'cuda') { $useGpu = $true }
    if ($Device -eq 'cpu') { $useGpu = $false }
    if ($Device -eq 'cuda' -and $null -eq $Hardware.GPU) { throw 'No se detecto una GPU NVIDIA. Elige CPU o instala el controlador.' }
    $provider = $Translation
    if ($provider -eq 'Auto') {
        $provider = 'none'
        if ($useGpu) {
            $provider = 'nllb'
            if ($Hardware.Ollama -and $Hardware.GPU.FreeMB -ge 5000) { $provider = 'llm' }
        }
    }
    $asrDevice = if ($useGpu) { 'cuda' } else { 'cpu' }
    $mtDevice = if ($useGpu -and $Hardware.GPU.FreeMB -ge 4000) { 'cuda' } else { 'cpu' }
    [ordered]@{
        YOUJP_ASR_DEVICE = $asrDevice
        YOUJP_ASR_MODEL = $(if ($useGpu) { 'large-v3-turbo' } else { 'small' })
        YOUJP_ASR_COMPUTE_TYPE = $(if ($useGpu) { 'int8_float16' } else { 'int8' })
        YOUJP_MT_PROVIDER = $provider
        YOUJP_MT_DEVICE = $mtDevice
        YOUJP_MT_COMPUTE_TYPE = $(if ($mtDevice -eq 'cuda') { 'int8_float16' } else { 'int8' })
        YOUJP_LLM_NUM_GPU = $(if ($useGpu) { '99' } else { '0' })
    }
}

function Invoke-YouJPCommand {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Fallo ($LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

function Get-YouJPVersion {
    (Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'VERSION') -Raw).Trim()
}

function Get-YouJPRuntime {
    $path = Join-Path $script:RuntimeDir 'runtime.json'
    if (Test-Path -LiteralPath $path) { return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json }
    [pscustomobject]@{ port = 8770; app_version = ''; asr_device = ''; mt_provider = '' }
}

function Test-YouJPHealth {
    param($Health)
    if ($null -eq $Health) { return $false }
    $properties = @($Health.PSObject.Properties.Name)
    $protocol = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'protocol/schema.json') -Raw | ConvertFrom-Json
    return ('service' -in $properties -and 'protocol_version' -in $properties -and
        'app_version' -in $properties -and 'asr_loaded' -in $properties -and
        $Health.service -eq 'youjp' -and $Health.asr_loaded -and
        $Health.protocol_version -eq $protocol.'x-youjp'.protocol_version -and
        $Health.app_version -eq (Get-YouJPVersion))
}
