param([switch]$Download)
$ErrorActionPreference = 'Stop'
$taskWorkspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$taskRuntimeRoot = Join-Path $taskWorkspace '.youjp\trials\asr'
$taskModelRoot = Join-Path $taskWorkspace 'models\trials\nemotron-3.5-asr'
$taskZip = Join-Path $taskRuntimeRoot 'nemo-speech-0.2.0-windows-x86_64-cuda.zip'
$taskModel = Join-Path $taskModelRoot 'nemotron-3.5-asr-streaming-0.6b.q8_0.gguf'
$taskZipHash = '9ffe5e842c39a7d3211f3b2c3b3aa1bca8c0b2455d96d961ed5f22ec5108f98d'
$taskModelHash = '3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1'
New-Item -ItemType Directory -Force -Path $taskRuntimeRoot,$taskModelRoot | Out-Null
if ($Download) {
    & curl.exe -fL --retry 3 --connect-timeout 20 --max-time 900 -C - -o $taskZip 'https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v0.2.0/nemo-speech-0.2.0-windows-x86_64-cuda.zip'
    if ($LASTEXITCODE -ne 0) { throw 'Runtime download failed' }
    & curl.exe -fL --retry 3 --connect-timeout 20 --max-time 900 -C - -o $taskModel 'https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b/resolve/ea30d66/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf'
    if ($LASTEXITCODE -ne 0) { throw 'Model download failed' }
}
if ((Get-FileHash -LiteralPath $taskZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskZipHash) { throw 'Runtime SHA256 mismatch' }
if ((Get-Item -LiteralPath $taskModel).Length -ne 742090464) { throw 'Model size mismatch' }
if ((Get-FileHash -LiteralPath $taskModel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskModelHash) { throw 'Model SHA256 mismatch' }
$taskExtractRoot = [IO.Path]::GetFullPath((Join-Path $taskRuntimeRoot 'runtime'))
if (!$taskExtractRoot.StartsWith($taskWorkspace + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Extraction target is outside workspace' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$taskArchive = [IO.Compression.ZipFile]::OpenRead($taskZip)
try {
    foreach ($taskEntry in $taskArchive.Entries) {
        $taskEntryTarget = [IO.Path]::GetFullPath((Join-Path $taskExtractRoot $taskEntry.FullName))
        if (!$taskEntryTarget.StartsWith($taskExtractRoot + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe path in release archive' }
    }
} finally { $taskArchive.Dispose() }
Expand-Archive -LiteralPath $taskZip -DestinationPath $taskExtractRoot -Force
Get-ChildItem -LiteralPath $taskExtractRoot -Filter 'nemo-speech.exe' -Recurse | Select-Object FullName
Get-Item -LiteralPath $taskZip,$taskModel | Select-Object FullName,Length
