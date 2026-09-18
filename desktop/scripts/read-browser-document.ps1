param([Parameter(Mandatory=$true)][long]$WindowHandle)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
try {
    $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$WindowHandle)
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Document)
    $documents = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    $best = ''
    foreach ($document in $documents) {
        if ($document.Current.IsOffscreen) { continue }
        $pattern = $null
        if ($document.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$pattern)) {
            $value = $pattern.DocumentRange.GetText(24000)
            if ($value.Length -gt $best.Length) { $best = $value }
        }
        if ($best.Length -ge 80) { break }
        # Chromium can expose text nodes even when Document has no TextPattern.
        $texts = $document.FindAll([System.Windows.Automation.TreeScope]::Descendants,
            [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                [System.Windows.Automation.ControlType]::Text))
        $builder = [System.Text.StringBuilder]::new()
        foreach ($item in $texts) {
            $value = $item.Current.Name
            if ($value) { [void]$builder.AppendLine($value) }
            if ($builder.Length -ge 24000) { break }
        }
        if ($builder.Length -gt $best.Length) { $best = $builder.ToString() }
        if ($best.Length -ge 80) { break }
    }
    @{text=$best} | ConvertTo-Json -Compress
} catch {
    @{text='';error=$_.Exception.Message} | ConvertTo-Json -Compress
}
