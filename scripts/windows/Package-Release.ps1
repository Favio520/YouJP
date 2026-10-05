<#
.SYNOPSIS
  Genera el paquete de Windows: zip, SHA256SUMS y, si hay Inno Setup, el instalador.
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -STA -File scripts/windows/Package-Release.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -STA -File scripts/windows/Package-Release.ps1 -SkipInstaller -SkipExtensionBuild
#>
param(
    [string]$OutputDir,
    [switch]$SkipInstaller,
    [switch]$SkipExtensionBuild,
    [string]$ChromeStoreId = '',
    [string]$EdgeStoreId = ''
)
. (Join-Path $PSScriptRoot 'Common.ps1')
$root = $script:ProjectRoot
$version = Get-YouJPVersion
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'VERSION invalido.' }
if (-not $OutputDir) { $OutputDir = Join-Path $root 'dist' }
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$stageRoot = Join-Path $OutputDir 'stage'
$stage = Join-Path $stageRoot 'YouJP'
if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

function Invoke-Child {
    param([string[]]$Arguments)
    Invoke-YouJPCommand -Exe $script:PowerShellExe -Arguments (@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA') + $Arguments)
}

# 1. Lanzador e iconos (los iconos de la extension salen de aqui: van antes de compilarla).
Write-Output '==> Lanzador'
Invoke-Child @('-File', (Join-Path $PSScriptRoot 'Build-Launcher.ps1'), '-OutputPath', (Join-Path $stage 'YouJP.exe'))

# 2. Extension compilada, con la clave del manifest (ID estable que acepta el backend).
$built = Join-Path $root 'extension/.output/chrome-mv3'
if (-not $SkipExtensionBuild) {
    Write-Output '==> Extension'
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    Push-Location (Join-Path $root 'extension')
    try {
        if (-not (Test-Path -LiteralPath 'node_modules')) { Invoke-YouJPCommand -Exe $npm -Arguments @('ci', '--no-audit', '--no-fund') }
        Invoke-YouJPCommand -Exe $npm -Arguments @('run', 'build')
    } finally { Pop-Location }
}
$manifest = Join-Path $built 'manifest.json'
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "Falta $manifest. Compila la extension." }
$manifestData = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
if ($manifestData.version -ne $version) { throw "La extension compilada es $($manifestData.version), pero VERSION es $version." }
if ('key' -notin $manifestData.PSObject.Properties.Name) { throw 'La extension compilada no lleva key: el backend no aceptaria su ID.' }

# 3. Copia de ficheros. Sin modelos, entornos, pruebas ni datos del equipo de desarrollo.
Write-Output '==> Copiando ficheros'
function Copy-Tree {
    param([string]$From, [string]$To)
    $source = (Get-Item -LiteralPath $From).FullName.TrimEnd('\')
    Get-ChildItem -LiteralPath $source -Recurse -File -Force | ForEach-Object {
        $relative = $_.FullName.Substring($source.Length + 1)
        if ($relative -match '(^|\\)__pycache__\\' -or $_.Extension -in '.pyc', '.pyo') { return }
        $target = Join-Path $To $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target
    }
}
Copy-Tree (Join-Path $root 'backend/youjp') (Join-Path $stage 'backend/youjp')
foreach ($file in 'backend/pyproject.toml', 'backend/uv.lock', 'protocol/schema.json', 'VERSION', 'YouJP.cmd',
    'README.md', '.env.example', 'scripts/prepare_runtime.py', 'scripts/fetch_models.py', 'scripts/fetch_dicts.py') {
    $target = Join-Path $stage $file
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    Copy-Item -LiteralPath (Join-Path $root $file) -Destination $target
}
# Pruebas y vistas previas son de desarrollo; el resto lo necesita el lanzador.
Copy-Tree (Join-Path $root 'scripts/windows') (Join-Path $stage 'scripts/windows')
foreach ($dev in 'Test-Launcher.ps1', 'Render-Preview.ps1', 'Package-Release.ps1') {
    Remove-Item -LiteralPath (Join-Path $stage "scripts/windows/$dev") -Force -ErrorAction SilentlyContinue
}
Copy-Tree $built (Join-Path $stage 'extension/.output/chrome-mv3')

# 4. Zip.
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$zipPath = Join-Path $OutputDir "YouJP-$version-win-x64.zip"
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
# CreateFromDirectory de .NET Framework escribe "\" en los nombres: se usa "/", como pide el formato zip.
$archive = [IO.Compression.ZipFile]::Open($zipPath, 'Create')
try {
    $base = (Get-Item -LiteralPath $stageRoot).FullName.TrimEnd([char]92)
    foreach ($file in Get-ChildItem -LiteralPath $stageRoot -Recurse -File -Force) {
        $entry = $file.FullName.Substring($base.Length + 1).Replace([string][char]92, '/')
        $null = [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $entry, [IO.Compression.CompressionLevel]::Optimal)
    }
} finally { $archive.Dispose() }
Write-Output "Zip: $zipPath"

# 5. Instalador (Inno Setup).
$installerPath = $null
if (-not $SkipInstaller) {
    $iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $candidates = @($(if ($iscc) { $iscc.Source }),
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        (Get-ChildItem -Path "${env:ProgramFiles(x86)}\Inno Setup*", "$env:ProgramFiles\Inno Setup*" -Filter ISCC.exe -ErrorAction SilentlyContinue |
            ForEach-Object FullName)) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    if (-not $candidates) { throw 'No se encontro Inno Setup 6 (ISCC.exe). Instalalo o usa -SkipInstaller.' }
    Write-Output '==> Instalador'
    $isccArgs = @("/DAppVersion=$version", "/DSourceDir=$stage", "/DOutputDir=$OutputDir")
    if ($ChromeStoreId) { $isccArgs += "/DChromeStoreId=$ChromeStoreId" }
    if ($EdgeStoreId) { $isccArgs += "/DEdgeStoreId=$EdgeStoreId" }
    Invoke-YouJPCommand -Exe @($candidates)[0] -Arguments ($isccArgs + (Join-Path $root 'installer/YouJP.iss'))
    $installerPath = Join-Path $OutputDir "YouJP-Setup-$version.exe"
    if (-not (Test-Path -LiteralPath $installerPath)) { throw 'Inno Setup no genero el instalador.' }
}

$sums = foreach ($file in @($zipPath, $installerPath) | Where-Object { $_ }) {
    '{0}  {1}' -f (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant(), (Split-Path $file -Leaf)
}
[IO.File]::WriteAllLines((Join-Path $OutputDir 'SHA256SUMS.txt'), $sums, [Text.UTF8Encoding]::new($false))
Remove-Item -LiteralPath $stageRoot -Recurse -Force
Write-Output "Listo en $OutputDir"
$sums
