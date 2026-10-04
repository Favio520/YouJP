# Shared launcher strings. Unknown diagnostics remain visible in their original language.
$script:UiLanguage = 'es'
$script:EnglishStrings = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'locales/en.json') -Raw -Encoding UTF8 | ConvertFrom-Json
function Get-YouJPText([string]$Text) {
    if (-not $Text -or $script:UiLanguage -ne 'en') { return $Text }
    $entry = $script:EnglishStrings.PSObject.Properties[$Text]
    if ($entry) { return [string]$entry.Value }
    if ($Text -match '^Hay (\d+) pestañas conectadas\. Sigue los subtítulos desde YouTube\.$') {
        return "$($Matches[1]) tabs are connected. Follow the subtitles on YouTube."
    }
    if ($Text -match '^(\d+) frases$') { return "$($Matches[1]) sentences" }
    if ($Text -match '^(\d+) de 2 pasos$') { return "$($Matches[1]) of 2 steps" }
    if ($Text -match '^El puerto (\d+) ya está ocupado\.') { return "Port $($Matches[1]) is busy. Check Activity before starting." }
    return $Text
}

$script:LocalizedControls = @{}
function Set-YouJPViewLanguage($Root) {
    if ($null -eq $Root -or $Root -is [string]) { return }
    foreach ($property in @('Text', 'Content', 'Header', 'ToolTip')) {
        # Selection/input text is state, not a static label. Restoring it can
        # select the previous language and recursively fire SelectionChanged.
        if ($property -eq 'Text' -and ($Root -is [Windows.Controls.ComboBox] -or $Root -is [Windows.Controls.TextBox])) { continue }
        if ($Root.PSObject.Properties.Name -contains $property -and $Root.$property -is [string]) {
            $key = "$($Root.GetHashCode()):$property"
            if (-not $script:LocalizedControls.ContainsKey($key)) { $script:LocalizedControls[$key] = $Root.$property }
            $Root.$property = Get-YouJPText $script:LocalizedControls[$key]
        }
    }
    if ($Root -is [Windows.DependencyObject]) {
        $name = [Windows.Automation.AutomationProperties]::GetName($Root)
        if ($name) {
            $key = "$($Root.GetHashCode()):AutomationName"
            if (-not $script:LocalizedControls.ContainsKey($key)) { $script:LocalizedControls[$key] = $name }
            [Windows.Automation.AutomationProperties]::SetName($Root, (Get-YouJPText $script:LocalizedControls[$key]))
        }
        foreach ($child in [Windows.LogicalTreeHelper]::GetChildren($Root)) { Set-YouJPViewLanguage $child }
    }
}
