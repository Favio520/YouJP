<#
.SYNOPSIS
  Tareas del proyecto. Ejecutar desde la raiz del repositorio.

.EXAMPLE
  .\tasks.ps1 setup            # entorno + modelos
  .\tasks.ps1 test             # tests del backend
  .\tasks.ps1 bench            # banco de latencia sobre bench/samples
  .\tasks.ps1 bench -Fast      # banco de RTF (sin pacing)
  .\tasks.ps1 gpu              # estado de la GPU
  .\tasks.ps1 doctor           # comprueba que todo esta en su sitio
#>
param(
  [Parameter(Position = 0)][ValidateSet('setup', 'test', 'bench', 'gpu', 'doctor')]
  [string]$Task = 'doctor',
  [switch]$Fast,
  [string]$Model
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Backend = Join-Path $Root 'backend'

function Invoke-Setup {
  Push-Location $Backend
  try {
    Write-Host '==> entorno de Python' -ForegroundColor Cyan
    uv sync --extra cuda
    Write-Host '==> modelos' -ForegroundColor Cyan
    uv run python ../scripts/fetch_models.py --whisper large-v3-turbo
  } finally { Pop-Location }
}

function Invoke-Test {
  Push-Location $Backend
  try { uv run pytest } finally { Pop-Location }
}

function Invoke-Bench {
  Push-Location $Backend
  try {
    $argv = @('run', 'python', '../scripts/bench_latency.py')
    if ($Fast) { $argv += '--fast' }
    if ($Model) { $argv += @('--model', $Model) }
    & uv @argv
  } finally { Pop-Location }
}

function Invoke-Gpu {
  nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu `
    --format=csv,noheader
}

function Invoke-Doctor {
  $ok = $true
  function Check($label, [scriptblock]$test, $hint) {
    try { $value = & $test } catch { $value = $null }
    if ($value) {
      Write-Host ("  [ok]   {0,-22} {1}" -f $label, $value) -ForegroundColor Green
    } else {
      Write-Host ("  [falta] {0,-21} {1}" -f $label, $hint) -ForegroundColor Yellow
      $script:ok = $false
    }
  }

  Write-Host 'herramientas' -ForegroundColor Cyan
  Check 'uv'        { (Get-Command uv -ErrorAction SilentlyContinue).Source } 'https://docs.astral.sh/uv/'
  Check 'ffmpeg'    { (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source } 'winget install Gyan.FFmpeg'
  Check 'nvidia-smi' { (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source } 'instala el driver de NVIDIA'

  Write-Host 'entorno' -ForegroundColor Cyan
  Check 'venv'      { if (Test-Path "$Backend\.venv") { "$Backend\.venv" } } '.\tasks.ps1 setup'
  Check 'CUDA dlls' {
    $p = Get-ChildItem "$Backend\.venv\Lib\site-packages\nvidia" -Directory -ErrorAction SilentlyContinue
    if ($p) { ($p | ForEach-Object Name) -join ', ' }
  } 'uv sync --extra cuda'

  Write-Host 'modelos y datos' -ForegroundColor Cyan
  Check 'silero_vad.onnx' {
    $f = Join-Path $Root 'models\silero_vad.onnx'
    if (Test-Path $f) { "{0:N0} KB" -f ((Get-Item $f).Length / 1KB) }
  } 'uv run python ../scripts/fetch_models.py'
  Check 'whisper'   {
    $d = Join-Path $Root 'models\whisper'
    if (Test-Path $d) { "{0:N0} MB" -f ((Get-ChildItem $d -Recurse -File | Measure-Object Length -Sum).Sum / 1MB) }
  } 'uv run python ../scripts/fetch_models.py --whisper large-v3-turbo'
  Check 'muestras'  {
    $n = (Get-ChildItem (Join-Path $Root 'bench\samples') -Filter *.wav -ErrorAction SilentlyContinue).Count
    if ($n -gt 0) { "$n .wav" }
  } '.\scripts\prepare_sample.ps1 -Input <fichero> -Duration 60'

  Write-Host 'gpu' -ForegroundColor Cyan
  Check 'VRAM libre' { Invoke-Gpu } 'sin GPU accesible'

  if ($ok) { Write-Host "`nTodo listo." -ForegroundColor Green }
  else { Write-Host "`nFalta algo de lo marcado arriba." -ForegroundColor Yellow }
}

switch ($Task) {
  'setup'  { Invoke-Setup }
  'test'   { Invoke-Test }
  'bench'  { Invoke-Bench }
  'gpu'    { Invoke-Gpu }
  'doctor' { Invoke-Doctor }
}
