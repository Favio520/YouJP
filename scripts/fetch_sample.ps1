<#
.SYNOPSIS
  Extrae un tramo de audio de un vídeo de YouTube y lo deja listo para el banco.

.DESCRIPTION
  Descarga solo el intervalo pedido (no el vídeo entero) y lo convierte a WAV
  mono de 16 kHz, que es el formato exacto con el que trabajará la extensión.
  El audio se queda en bench/samples y no se versiona.

  Para directos en curso, --download-sections no funciona: usa -Live, que graba
  los segundos indicados desde el punto actual de la emisión.

.EXAMPLE
  .\scripts\fetch_sample.ps1 -Url "https://youtu.be/XXXX" -Name noticias -Start 00:01:30 -Duration 60
  .\scripts\fetch_sample.ps1 -Url "https://youtu.be/XXXX" -Name directo -Duration 90 -Live

.NOTES
  Las llamadas a yt-dlp y ffmpeg pasan por Invoke-Native. Los dos escriben su
  progreso en stderr, y en PowerShell 5.1 eso se convierte en ErrorRecord: con
  $ErrorActionPreference = 'Stop' el script abortaria aunque el programa hubiera
  terminado con exito. Lo unico fiable de un ejecutable nativo es $LASTEXITCODE.
#>
param(
  [Parameter(Mandatory = $true)][string]$Url,
  [Parameter(Mandatory = $true)][string]$Name,
  [string]$Start = "00:00:00",
  [int]$Duration = 60,
  [switch]$Live,
  [switch]$ShowOutput,
  [string]$OutDir = "$PSScriptRoot\..\bench\samples"
)
# Ojo: el conmutador se llama -ShowOutput y no -Verbose porque -Verbose es un
# parametro comun de PowerShell y redefinirlo hace que el script no se pueda
# invocar. Misma trampa que -Input en prepare_sample.ps1.

$ErrorActionPreference = 'Stop'

function Invoke-Native {
  param([string]$Exe, [string[]]$Arguments, [switch]$Show)
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    if ($Show) { & $Exe @Arguments } else { & $Exe @Arguments 2>$null | Out-Null }
    if ($LASTEXITCODE -ne 0) { throw "$Exe fallo con codigo $LASTEXITCODE" }
  } finally {
    $ErrorActionPreference = $prev
  }
}

foreach ($tool in 'yt-dlp', 'ffmpeg', 'node') {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    throw "$tool no esta en el PATH."
  }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$out = Join-Path (Resolve-Path $OutDir) "$Name.wav"
$tmp = Join-Path $env:TEMP "youjp-$Name-$(Get-Random)"

# yt-dlp necesita un runtime de JavaScript para extraer de YouTube y solo activa
# deno por defecto. Sin esto falla con "No supported JavaScript runtime".
$common = @('--js-runtimes', 'node', '--no-warnings', '--no-progress', '-f', 'bestaudio')

try {
  if ($Live) {
    # En un directo no hay linea temporal sobre la que cortar: se graba desde el
    # punto actual y se para a los N segundos.
    Write-Host "grabando $Duration s del directo..." -ForegroundColor Cyan
    Invoke-Native yt-dlp ($common + @(
        '--no-part', '-o', "$tmp.%(ext)s",
        '--downloader', 'ffmpeg', '--downloader-args', "ffmpeg:-t $Duration", $Url
      )) -Show:$ShowOutput
  } else {
    $t0 = [TimeSpan]::Parse($Start)
    $t1 = $t0.Add([TimeSpan]::FromSeconds($Duration))
    $section = "*{0:hh\:mm\:ss}-{1:hh\:mm\:ss}" -f $t0, $t1
    Write-Host "descargando tramo $section ..." -ForegroundColor Cyan
    Invoke-Native yt-dlp ($common + @(
        '--download-sections', $section, '-o', "$tmp.%(ext)s", $Url
      )) -Show:$ShowOutput
  }

  $downloaded = Get-ChildItem "$tmp.*" -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $downloaded) { throw "yt-dlp no dejo ningun fichero en $tmp.*" }

  Invoke-Native ffmpeg @(
    '-y', '-hide_banner', '-loglevel', 'error', '-i', $downloaded.FullName,
    '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', $out
  )

  $secs = (Get-Item $out).Length / (16000 * 2)
  "{0}  ({1:N1} s, 16 kHz mono)" -f $out, $secs
} finally {
  Remove-Item "$tmp.*" -Force -ErrorAction SilentlyContinue
}
