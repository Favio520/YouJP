# Renderizar el XAML de la app en archivos locales, sin capturar el escritorio.
param([ValidateSet('idle', 'ready', 'capturing', 'starting', 'setup', 'error', 'unprepared')][string]$State = 'ready')
. (Join-Path $PSScriptRoot 'YouJP.ps1') -SmokeTest
$script:previewKind = $State
Update-Panel
$previewDir = Join-Path $script:RuntimeDir 'ui-previews'
New-Item -ItemType Directory -Force -Path $previewDir | Out-Null
foreach ($size in @(@(1100, 760), @(880, 580))) {
    foreach ($page in @('home', 'settings', 'activity')) {
        Show-Page $page
        $surface = $window.Content
        $surface.Measure([Windows.Size]::new($size[0], $size[1]))
        $surface.Arrange([Windows.Rect]::new(0, 0, $size[0], $size[1]))
        $surface.UpdateLayout()
        $image = [Windows.Media.Imaging.RenderTargetBitmap]::new($size[0], $size[1], 96, 96, [Windows.Media.PixelFormats]::Pbgra32)
        $image.Render($surface)
        $encoder = [Windows.Media.Imaging.PngBitmapEncoder]::new()
        $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($image))
        $output = Join-Path $previewDir "$page-$State-$($size[0]).png"
        $stream = [IO.File]::Create($output)
        try { $encoder.Save($stream) } finally { $stream.Dispose() }
        Write-Output $output
    }
}
