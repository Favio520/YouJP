# Emblema vectorial de YouJP para Windows.
. (Join-Path $PSScriptRoot 'Common.ps1')
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
$assetDir = Join-Path $PSScriptRoot 'assets'
$reader = [Xml.XmlNodeReader]::new([xml][IO.File]::ReadAllText((Join-Path $assetDir 'BrandLogo.xaml')))
try { $drawing = [Windows.Markup.XamlReader]::Load($reader) } finally { $reader.Close() }
$frames = @()
foreach ($size in @(16, 20, 24, 32, 40, 48, 64, 96, 128, 256)) {
    $visual = [Windows.Media.DrawingVisual]::new()
    $context = $visual.RenderOpen()
    $sourceImage = $drawing
    $context.DrawImage($sourceImage, [Windows.Rect]::new(0, 0, $size, $size))
    $context.Close()
    $bitmap = [Windows.Media.Imaging.RenderTargetBitmap]::new($size, $size, 96, 96, [Windows.Media.PixelFormats]::Pbgra32)
    $bitmap.Render($visual)
    $encoder = [Windows.Media.Imaging.PngBitmapEncoder]::new()
    $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
    $stream = [IO.MemoryStream]::new()
    $encoder.Save($stream)
    $bytes = $stream.ToArray()
    $frames += [pscustomobject]@{ Size = $size; Bytes = $bytes }
    if ($size -eq 256) { [IO.File]::WriteAllBytes((Join-Path $assetDir 'app-logo.png'), $bytes) }
    $stream.Dispose()
}
$iconPath = Join-Path $assetDir 'youjp-logo.ico'
$icon = [IO.BinaryWriter]::new([IO.File]::Create($iconPath))
try {
    $icon.Write([uint16]0); $icon.Write([uint16]1); $icon.Write([uint16]$frames.Count)
    $offset = 6 + 16 * $frames.Count
    foreach ($frame in $frames) {
        $dimension = if ($frame.Size -eq 256) { 0 } else { $frame.Size }
        $icon.Write([byte]$dimension); $icon.Write([byte]$dimension)
        $icon.Write([byte]0); $icon.Write([byte]0)
        $icon.Write([uint16]1); $icon.Write([uint16]32)
        $icon.Write([uint32]$frame.Bytes.Length); $icon.Write([uint32]$offset)
        $offset += $frame.Bytes.Length
    }
    foreach ($frame in $frames) { $icon.Write([byte[]]$frame.Bytes) }
} finally { $icon.Dispose() }
Write-Output 'Emblema de YouJP listo para Windows.'
