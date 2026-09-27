param([switch]$SkipIcons)
# Compilar el lanzador nativo con .NET Framework incluido en Windows.
. (Join-Path $PSScriptRoot 'Common.ps1')
if (-not $SkipIcons) { . (Join-Path $PSScriptRoot 'Build-Icons.ps1') }
$assetDir = Join-Path $PSScriptRoot 'assets'
$iconPath = Join-Path $assetDir 'youjp.ico'

$buildDir = Join-Path $script:RuntimeDir 'build'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$version = Get-YouJPVersion
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid VERSION for the Windows executable.' }
$metadata = @"
using System.Reflection;
[assembly: AssemblyTitle("YouJP")]
[assembly: AssemblyProduct("YouJP")]
[assembly: AssemblyDescription("Japanese subtitles, in context")]
[assembly: AssemblyVersion("$version.0")]
[assembly: AssemblyFileVersion("$version.0")]
"@
$metadataPath = Join-Path $buildDir 'Version.cs'
[IO.File]::WriteAllText($metadataPath, $metadata)
$compiler = Join-Path ([Environment]::GetFolderPath('Windows')) 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$automation = [Management.Automation.PowerShell].Assembly.Location
$exePath = Join-Path $script:ProjectRoot 'YouJP.exe'
Invoke-YouJPCommand -Exe $compiler -Arguments @('/nologo', '/codepage:65001', '/target:winexe', '/platform:anycpu', '/optimize+',
    "/out:$exePath", "/win32icon:$iconPath", "/win32manifest:$(Join-Path $PSScriptRoot 'YouJP.manifest')",
    '/reference:System.Windows.Forms.dll', "/reference:$automation",
    (Join-Path $PSScriptRoot 'Launcher.cs'), $metadataPath)
Write-Output "Built YouJP.exe $version with a native application icon."
