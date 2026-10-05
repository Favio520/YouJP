<# Primera preparación lanzada por el instalador: muestra el progreso y deja registro. #>
$Host.UI.RawUI.WindowTitle = 'YouJP: preparando'
$logDir = Join-Path ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))) '.youjp'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'install-firstrun.log'
Write-Host 'YouJP va a descargar los modelos y dependencias que necesita. No cierres esta ventana.' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'Setup.ps1') *>&1 | Tee-Object -FilePath $log
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host ''
    Write-Host 'La preparacion no termino. Puedes reintentarla desde YouJP con "Preparar / actualizar".' -ForegroundColor Yellow
    Write-Host "Registro: $log"
    Read-Host 'Pulsa Intro para cerrar'
}
exit $code
