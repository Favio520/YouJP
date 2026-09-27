# Solo estado visual; YouJP.ps1 conserva los procesos y las consultas de salud.
function Get-YouJPPanelState {
    param(
        [bool]$Installed, [bool]$Checked, [bool]$Owned,
        [bool]$SettingUp, [bool]$Stopping, [bool]$Ready,
        [bool]$Conflict, [int]$Sessions = 0, [string]$Failure = ''
    )
    $view = @{
        Kind = 'idle'; Label = 'En espera'; Title = 'Dale oído a tu japonés.'
        Detail = 'Inicia YouJP y abre un vídeo en japonés. Los subtítulos aparecerán al activar la extensión.'
        Primary = 'Iniciar YouJP'; Action = 'start'; Tone = 'neutral'; Busy = $false
        CanAct = $true; CanStop = $Owned -and -not $Stopping
        CanSetup = $Checked -and -not ($Owned -or $SettingUp -or $Ready -or $Conflict)
    }
    if ($SettingUp) {
        $view.Kind = 'setup'; $view.Label = 'Preparando'; $view.Title = 'Estamos preparando tu equipo.'
        $view.Detail = 'Descargando los modelos y preparando la extensión. Puedes seguir el progreso en Actividad.'
        $view.Primary = 'Preparando…'; $view.Busy = $true; $view.CanAct = $false; $view.Tone = 'blue'
    } elseif ($Stopping) {
        $view.Kind = 'stopping'; $view.Label = 'Deteniendo'; $view.Title = 'Cerrando la sesión.'
        $view.Detail = 'YouJP está liberando los modelos y los recursos de tu equipo.'
        $view.Primary = 'Deteniendo…'; $view.Busy = $true; $view.CanAct = $false; $view.Tone = 'blue'
    } elseif ($Ready) {
        $view.Kind = 'ready'; $view.Label = 'Listo'; $view.Title = 'Todo listo. Dale al play.'
        $view.Detail = 'Abre un vídeo en japonés y pulsa el icono de YouJP en el navegador para activar los subtítulos.'
        $view.Primary = 'Abrir YouTube'; $view.Action = 'youtube'; $view.Tone = 'green'
        if ($Sessions -gt 0) {
            $view.Kind = 'capturing'; $view.Label = 'Conectado'; $view.Title = 'El japonés, frase a frase.'
            $view.Detail = if ($Sessions -eq 1) { 'Hay una pestaña conectada. Sigue los subtítulos y explora las palabras desde YouTube.' }
                else { "Hay $Sessions pestañas conectadas. Sigue los subtítulos desde YouTube." }
        }
    } elseif ($Owned) {
        $view.Kind = 'starting'; $view.Label = 'Iniciando'; $view.Title = 'Preparando tus subtítulos.'
        $view.Detail = 'Cargando los modelos en tu equipo. El primer inicio puede tardar unos minutos.'
        $view.Primary = 'Iniciando…'; $view.Busy = $true; $view.CanAct = $false; $view.Tone = 'blue'
    } elseif ($Conflict) {
        $view.Kind = 'conflict'; $view.Label = 'Revisar conexión'; $view.Title = 'No podemos conectar con YouJP.'
        $view.Detail = 'Hay otro servicio o una versión incompatible en el puerto configurado. Revisa los registros antes de iniciar.'
        $view.Primary = 'Ver actividad'; $view.Action = 'activity'; $view.Tone = 'red'
    } elseif ($Failure) {
        $view.Kind = 'error'; $view.Label = 'Necesita atención'; $view.Title = 'Algo no salió como esperábamos.'
        $view.Detail = $Failure; $view.Primary = 'Volver a intentar'; $view.Tone = 'red'
        if (-not $Installed) { $view.Action = 'settings'; $view.Primary = 'Revisar configuración' }
    } elseif (-not $Checked) {
        $view.Kind = 'checking'; $view.Label = 'Comprobando'; $view.Title = 'Un momento, estamos comprobando todo.'
        $view.Detail = 'Buscando una sesión de YouJP en este equipo.'
        $view.Primary = 'Comprobando…'; $view.Busy = $true; $view.CanAct = $false; $view.Tone = 'blue'
    } elseif (-not $Installed) {
        $view.Kind = 'unprepared'; $view.Label = 'Primer inicio'; $view.Title = 'Hagamos sitio al japonés.'
        $view.Detail = 'Prepara los modelos y la extensión una vez. Después, solo tendrás que iniciar YouJP.'
        $view.Primary = 'Preparar mi equipo'; $view.Action = 'settings'
    }
    return [pscustomobject]$view
}
