# Emblema de YouJP para Windows, generado desde assets/app-icon-sumi-e.png.
# Escala el mismo dibujo a todos los tamanos con WPF (sin Pillow ni navegador):
# app-logo.png para la ventana, youjp-logo.ico para el ejecutable y la bandeja, y
# los iconos de la extension, para que todo lleve la misma marca.
. (Join-Path $PSScriptRoot 'Common.ps1')
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
$assetDir = Join-Path $PSScriptRoot 'assets'
$source = [Windows.Media.Imaging.BitmapImage]::new()
$source.BeginInit()
$source.UriSource = [Uri]::new((Join-Path $assetDir 'app-icon-sumi-e.png'))
$source.CacheOption = 'OnLoad'
$source.EndInit()
$source.Freeze()

function Convert-ToPng([int]$Size) {
    $visual = [Windows.Media.DrawingVisual]::new()
    [Windows.Media.RenderOptions]::SetBitmapScalingMode($visual, 'HighQuality')
    $context = $visual.RenderOpen()
    $context.DrawImage($source, [Windows.Rect]::new(0, 0, $Size, $Size))
    $context.Close()
    $bitmap = [Windows.Media.Imaging.RenderTargetBitmap]::new($Size, $Size, 96, 96, [Windows.Media.PixelFormats]::Pbgra32)
    $bitmap.Render($visual)
    $encoder = [Windows.Media.Imaging.PngBitmapEncoder]::new()
    $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
    $stream = [IO.MemoryStream]::new()
    try { $encoder.Save($stream); return ,$stream.ToArray() } finally { $stream.Dispose() }
}

$icoSizes = @(16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
$extensionSizes = @(16, 32, 48, 96, 128)
$frames = @{}
foreach ($size in ($icoSizes + $extensionSizes | Sort-Object -Unique)) { $frames[$size] = Convert-ToPng $size }

[IO.File]::WriteAllBytes((Join-Path $assetDir 'app-logo.png'), $frames[256])
$icon = [IO.BinaryWriter]::new([IO.File]::Create((Join-Path $assetDir 'youjp-logo.ico')))
try {
    $icon.Write([uint16]0); $icon.Write([uint16]1); $icon.Write([uint16]$icoSizes.Count)
    $offset = 6 + 16 * $icoSizes.Count
    foreach ($size in $icoSizes) {
        $dimension = if ($size -eq 256) { 0 } else { $size }
        $icon.Write([byte]$dimension); $icon.Write([byte]$dimension)
        $icon.Write([byte]0); $icon.Write([byte]0)
        $icon.Write([uint16]1); $icon.Write([uint16]32)
        $icon.Write([uint32]$frames[$size].Length); $icon.Write([uint32]$offset)
        $offset += $frames[$size].Length
    }
    foreach ($size in $icoSizes) { $icon.Write([byte[]]$frames[$size]) }
} finally { $icon.Dispose() }

$extensionIcons = Join-Path $script:ProjectRoot 'extension/public/icon'
if (Test-Path -LiteralPath $extensionIcons -PathType Container) {
    foreach ($size in $extensionSizes) { [IO.File]::WriteAllBytes((Join-Path $extensionIcons "$size.png"), $frames[$size]) }
}
Write-Output 'Emblema de YouJP listo para Windows.'
