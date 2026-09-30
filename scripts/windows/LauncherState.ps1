if (-not (Get-Command Get-YouJPText -ErrorAction SilentlyContinue)) {
    . (Join-Path $PSScriptRoot 'Localization.ps1')
}
# Solo estado visual; YouJP.ps1 conserva los procesos y las consultas de salud.
function Get-YouJPPanelState {
    param(
        [bool]$Installed, [bool]$Checked, [bool]$Owned,
        [bool]$SettingUp, [bool]$Stopping, [bool]$Ready,
        [bool]$Conflict, [int]$Sessions = 0, [string]$Failure = ''
    )
    $view = @{
        Kind = 'idle'; Label = (Get-YouJPText 'En espera'); Title = (Get-YouJPText 'Dale oído a tu japonés.')
        Detail = (Get-YouJPText 'Inicia YouJP y abre un vídeo en japonés. Los subtítulos aparecerán al activar la extensión.')
        Primary = (Get-YouJPText 'Iniciar YouJP'); Action = 'start'; Tone = 'neutral'; Busy = $false
        CanAct = $true; CanStop = $Owned -and -not $Stopping
        CanSetup = $Checked -and -not ($Owned -or $SettingUp -or $Ready -or $Conflict)
    }
    if ($SettingUp) {
        $view.Kind = 'setup'; $view.Label = (Get-YouJPText 'Preparando'); $view.Title = (Get-YouJPText 'Estamos preparando tu equipo.')
        $view.Detail = (Get-YouJPText 'Descargando los modelos y preparando la extensión. Puedes seguir el progreso en Actividad.')
        $view.Primary = (Get-YouJPText 'Preparando…'); $view.Busy = $true; $view.CanAct = $false; $view.Tone = 'blue'
    } elseif ($Stopping) {
        $view.Kind = 'stopping'; $view.Label = (Get-YouJPText 'Deteniendo'); $view.Title = (Get-YouJPText 'Cerrando la sesión.')
        $view.Detail = (Get-YouJPText 'YouJP está liberando los modelos y los recursos de tu equipo.')
        $view.Primary = (Get-YouJPText 'Deteniendo…'); $view.Busy = $true; $view.CanAct = $false; $view.Tone = 'blue'
    } elseif ($Ready) {
        $view.Kind = 'ready'; $view.Label = (Get-YouJPText 'Listo'); $view.Title = (Get-YouJPText 'Todo listo. Dale al play.')
        $view.Detail = (Get-YouJPText 'Abre un vídeo en japonés y pulsa el icono de YouJP en el navegador para activar los subtítulos.')
        $view.Primary = (Get-YouJPText 'Abrir YouTube'); $view.Action = 'youtube'; $view.Tone = 'green'
        if ($Sessions -gt 0) {
            $view.Kind = 'capturing'; $view.Label = (Get-YouJPText 'Conectado'); $view.Title = (Get-YouJPText 'El japonés, frase a frase.')
            $view.Detail = if ($Sessions -eq 1) { (Get-YouJPText 'Hay una pestaña conectada. Sigue los subtítulos y explora las palabras desde YouTube.') }
                else { "Hay $Sessions pestañas conectadas. Sigue los subtítulos desde YouTube." }
        }
    } elseif ($Owned) {
        $view.Kind = 'starting'; $view.Label = (Get-YouJPText 'Iniciando'); $view.Title = (Get-YouJPText 'Preparando tus subtítulos.')
        $view.Detail = (Get-YouJPText 'Cargando los modelos en tu equipo. El primer inicio puede tardar unos minutos.')
        $view.Primary = (Get-YouJPText 'Iniciando…'); $view.Busy = $true; $view.CanAct = $false; $view.Tone = 'blue'
    } elseif ($Conflict) {
        $view.Kind = 'conflict'; $view.Label = (Get-YouJPText 'Revisar conexión'); $view.Title = (Get-YouJPText 'No podemos conectar con YouJP.')
        $view.Detail = (Get-YouJPText 'Hay otro servicio o una versión incompatible en el puerto configurado. Revisa los registros antes de iniciar.')
        $view.Primary = (Get-YouJPText 'Ver actividad'); $view.Action = 'activity'; $view.Tone = 'red'
    } elseif ($Failure) {
        $view.Kind = 'error'; $view.Label = (Get-YouJPText 'Necesita atención'); $view.Title = (Get-YouJPText 'Algo no salió como esperábamos.')
        $view.Detail = $Failure; $view.Primary = (Get-YouJPText 'Volver a intentar'); $view.Tone = 'red'
        if (-not $Installed) { $view.Action = 'settings'; $view.Primary = (Get-YouJPText 'Revisar configuración') }
    } elseif (-not $Checked) {
        $view.Kind = 'checking'; $view.Label = (Get-YouJPText 'Comprobando'); $view.Title = (Get-YouJPText 'Un momento, estamos comprobando todo.')
        $view.Detail = (Get-YouJPText 'Buscando una sesión de YouJP en este equipo.')
        $view.Primary = (Get-YouJPText 'Comprobando…'); $view.Busy = $true; $view.CanAct = $false; $view.Tone = 'blue'
    } elseif (-not $Installed) {
        $view.Kind = 'unprepared'; $view.Label = (Get-YouJPText 'Primer inicio'); $view.Title = (Get-YouJPText 'Hagamos sitio al japonés.')
        $view.Detail = (Get-YouJPText 'Prepara los modelos y la extensión una vez. Después, solo tendrás que iniciar YouJP.')
        $view.Primary = (Get-YouJPText 'Preparar mi equipo'); $view.Action = 'settings'
    }
    foreach ($key in @('Label', 'Title', 'Detail', 'Primary')) { $view[$key] = Get-YouJPText $view[$key] }
    return [pscustomobject]$view
}
