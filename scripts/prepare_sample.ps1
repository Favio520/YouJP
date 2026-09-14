<#
.SYNOPSIS
  Convierte cualquier fichero de audio o video a WAV mono de 16 kHz para el banco.

.DESCRIPTION
  El pipeline trabaja siempre a 16 kHz mono float32, igual que lo hara el
  AudioContext de la extension. Las muestras del banco tienen que estar en ese
  mismo formato para que lo que se mide aqui sea comparable con lo que pasara en
  vivo.

.EXAMPLE
  .\scripts\prepare_sample.ps1 -Source "D:\clips\noticias.mp4" -Name noticias
  .\scripts\prepare_sample.ps1 -Source "D:\clips\charla.m4a" -Name charla -Start 00:02:10 -Duration 60

.NOTES
  El parametro se llama -Source y no -Input a proposito: $Input es una variable
  automatica de PowerShell (el enumerador de la tuberia) y declararla como
  parametro da comportamientos raros dificiles de diagnosticar.
#>
param(
  [Parameter(Mandatory = $true)][string]$Source,
  [string]$Name,
  [string]$Start,
  [int]$Duration,
  [string]$OutDir = "$PSScriptRoot\..\bench\samples"
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  throw "ffmpeg no esta en el PATH."
}
if (-not (Test-Path $Source)) { throw "no existe: $Source" }
if (-not $Name) { $Name = [System.IO.Path]::GetFileNameWithoutExtension($Source) }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$out = Join-Path (Resolve-Path $OutDir) "$Name.wav"

$ffargs = @('-y', '-hide_banner', '-loglevel', 'error')
if ($Start) { $ffargs += @('-ss', $Start) }
$ffargs += @('-i', $Source)
if ($Duration) { $ffargs += @('-t', "$Duration") }
# pcm_s16le: soundfile lo lee sin dependencias extra y ocupa la mitad que float32.
$ffargs += @('-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', $out)

& ffmpeg @ffargs
if ($LASTEXITCODE -ne 0) { throw "ffmpeg fallo con codigo $LASTEXITCODE" }

$size = (Get-Item $out).Length / 1MB
$secs = (Get-Item $out).Length / (16000 * 2)
"{0}  ({1:N1} MB, {2:N1} s)" -f $out, $size, $secs
