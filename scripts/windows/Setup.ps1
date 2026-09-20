<# Re-runnable Windows setup. -Plan only detects hardware and prints the plan. #>
param(
    [ValidateSet('Auto', 'cuda', 'cpu')][string]$Device = 'Auto',
    [ValidateSet('Auto', 'llm', 'nllb', 'none')][string]$Translation = 'Auto',
    [switch]$SkipDictionary,
    [switch]$Plan
)
. (Join-Path $PSScriptRoot 'Common.ps1')
$hardware = Get-YouJPHardware
$profile = Get-YouJPProfile -Hardware $hardware -Device $Device -Translation $Translation
if ($Plan) {
    [pscustomobject]@{ version = Get-YouJPVersion; hardware = $hardware; defaults = $profile;
        note = 'Las variables del entorno y .env tienen prioridad. No se ha instalado nada.' } | ConvertTo-Json -Depth 5
    exit 0
}

New-Item -ItemType Directory -Force -Path $script:RuntimeDir | Out-Null
$setupLock = $null
$setupSucceeded = $false
try {
    $setupLock = [IO.File]::Open((Join-Path $script:RuntimeDir 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $config = Get-YouJPRuntime
    $listener = Get-NetTCPConnection -LocalPort $config.port -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw "Deten el servidor del puerto $($config.port) antes de instalar o actualizar." }
    [IO.File]::WriteAllText((Join-Path $script:RuntimeDir 'installed-version'), '')
    Write-Output 'Preparando YouJP. La primera descarga puede tardar varios minutos.'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $toolsDir = Join-Path $script:RuntimeDir 'tools'
    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
    $env:UV_CACHE_DIR = Join-Path $script:RuntimeDir 'uv-cache'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $script:RuntimeDir 'python'
    $env:PYTHONUTF8 = '1'
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    $uvPath = if ($uv) { $uv.Source } else { Join-Path $toolsDir 'uv.exe' }
    if (-not (Test-Path -LiteralPath $uvPath)) {
        Write-Output 'Instalando uv en la carpeta de YouJP...'
        $installer = Join-Path $toolsDir 'uv-install.ps1'
        Invoke-WebRequest 'https://astral.sh/uv/install.ps1' -UseBasicParsing -OutFile $installer
        $env:UV_INSTALL_DIR = $toolsDir
        $env:UV_NO_MODIFY_PATH = '1'
        Invoke-YouJPCommand -Exe $script:PowerShellExe -Arguments @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installer)
        if (-not (Test-Path -LiteralPath $uvPath)) { throw 'No se encontro uv despues de instalarlo.' }
    }
    Invoke-YouJPCommand -Exe $uvPath -Arguments @('python', 'install', '3.12')
    # This file only supplies defaults. Never rewrite a user's .env.
    $lines = @('# Generado por el asistente. .env y las variables del entorno tienen prioridad.')
    foreach ($key in $profile.Keys) { $lines += "$key=$($profile[$key])" }
    [IO.File]::WriteAllLines((Join-Path $script:RuntimeDir 'launcher.env'), $lines, [Text.UTF8Encoding]::new($false))
    Push-Location (Join-Path $script:ProjectRoot 'backend')
    try {
        $syncArgs = @('sync', '--locked', '--inexact', '--no-dev', '--python', '3.12')
        # Include CUDA libraries when a GPU exists, even if .env overrides Auto.
        if ($hardware.GPU -or $Device -eq 'cuda') { $syncArgs += @('--extra', 'cuda') }
        Invoke-YouJPCommand -Exe $uvPath -Arguments $syncArgs
        $python = Join-Path $script:ProjectRoot 'backend/.venv/Scripts/python.exe'
        $prepareArgs = @('-u', (Join-Path $script:ProjectRoot 'scripts/prepare_runtime.py'))
        if ($SkipDictionary) { $prepareArgs += '--skip-dictionary' }
        Invoke-YouJPCommand -Exe $python -Arguments $prepareArgs
    } finally { Pop-Location }

    Write-Output 'Preparando la extension...'
    $node = Get-Command node -ErrorAction SilentlyContinue
    $nodeDir = $null
    if ($node) {
        $major = [int]((& $node.Source --version).TrimStart('v').Split('.')[0])
        if ($major -ge 22) { $nodeDir = Split-Path $node.Source }
    }
    if (-not $nodeDir) {
        $releases = Invoke-RestMethod 'https://nodejs.org/dist/index.json'
        $release = $releases | Where-Object { $_.version -match '^v24\.' -and $_.lts } | Select-Object -First 1
        if (-not $release) { throw 'No se encontro Node.js 24 LTS para Windows.' }
        $archiveName = "node-$($release.version)-win-x64.zip"
        $nodeDir = Join-Path $toolsDir "node-$($release.version)-win-x64"
        if (-not (Test-Path -LiteralPath (Join-Path $nodeDir 'node.exe'))) {
            $base = "https://nodejs.org/dist/$($release.version)"
            $archive = Join-Path $toolsDir $archiveName
            Invoke-WebRequest "$base/$archiveName" -UseBasicParsing -OutFile $archive
            $checksums = (Invoke-WebRequest "$base/SHASUMS256.txt" -UseBasicParsing).Content
            $match = [regex]::Match($checksums, '(?m)^([a-f0-9]{64})\s+' + [regex]::Escape($archiveName) + '\r?$')
            if (-not $match.Success -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $match.Groups[1].Value) {
                throw 'La descarga de Node.js no coincide con su SHA-256 oficial.'
            }
            Expand-Archive -LiteralPath $archive -DestinationPath $toolsDir -Force
        }
    }
    $env:PATH = "$nodeDir;$env:PATH"
    Push-Location (Join-Path $script:ProjectRoot 'extension')
    try {
        $npm = Join-Path $nodeDir 'npm.cmd'
        Invoke-YouJPCommand -Exe $npm -Arguments @('ci', '--no-audit', '--no-fund')
        Invoke-YouJPCommand -Exe $npm -Arguments @('run', 'build')
    } finally { Pop-Location }
    # Written last: failed/partial installations must not look ready to launch.
    [IO.File]::WriteAllText((Join-Path $script:RuntimeDir 'installed-version'), (Get-YouJPVersion))
    Write-Output 'Listo. Inicia el backend y carga extension/.output/chrome-mv3 desde chrome://extensions.'
    $setupSucceeded = $true
} catch {
    Write-Output "ERROR: $($_.Exception.Message)"
} finally {
    if ($setupLock) { $setupLock.Dispose() }
}
if (-not $setupSucceeded) { exit 1 }
