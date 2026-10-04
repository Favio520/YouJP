# Renderizar el XAML de la app en archivos locales, sin capturar el escritorio.
param([ValidateSet('idle', 'ready', 'capturing', 'starting', 'setup', 'error', 'unprepared')][string]$State = 'ready',
    [ValidateSet('es', 'en')][string]$Language = 'es')
$renderLanguage = $Language
. (Join-Path $PSScriptRoot 'YouJP.ps1') -SmokeTest
$Language = $renderLanguage
$script:UiLanguage = $renderLanguage
$ui.UiLanguageChoice.SelectedIndex = if ($renderLanguage -eq 'en') { 1 } else { 0 }
Set-YouJPViewLanguage $window
$script:previewKind = $State
Update-Panel
$previewDir = Join-Path $script:RuntimeDir 'ui-previews'
New-Item -ItemType Directory -Force -Path $previewDir | Out-Null
foreach ($size in @(@(1180, 828), @(1120, 778), @(880, 580))) {
    foreach ($page in @('home', 'settings', 'activity', 'history')) {
        Show-Page $page
        $surface = $window.Content
        $surface.Measure([Windows.Size]::new($size[0], $size[1]))
        $surface.Arrange([Windows.Rect]::new(0, 0, $size[0], $size[1]))
        $surface.UpdateLayout()
        $image = [Windows.Media.Imaging.RenderTargetBitmap]::new($size[0], $size[1], 96, 96, [Windows.Media.PixelFormats]::Pbgra32)
        $image.Render($surface)
        $encoder = [Windows.Media.Imaging.PngBitmapEncoder]::new()
        $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($image))
        $output = Join-Path $previewDir "$page-$State-$Language-$($size[0]).png"
        $stream = [IO.File]::Create($output)
        try { $encoder.Save($stream) } finally { $stream.Dispose() }
        Write-Output $output
    }
}
