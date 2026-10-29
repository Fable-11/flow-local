# Stops a running Flow Local (source install or packaged build). Safe to run when it is not running.
# Only this project's own processes are touched: the packaged FlowLocal.exe, or a Python started
# from this folder with "-m flow" together with the interpreter it launches. Other Python programs
# are left alone. (-Root exists so the script can be tested on a stand-in folder.)
param([string]$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path)

$self = $PID
$all = Get-CimInstance Win32_Process
$flowCmd = '(^|[\s"\\])-m flow(\s|$)'

# a launcher lives inside this folder (the virtual environment's python); it starts the real
# interpreter as a child that lives elsewhere, so the children have to be stopped too
$launchers = $all | Where-Object {
    $_.ProcessId -ne $self -and $_.CommandLine -match $flowCmd -and $_.ExecutablePath -and
    $_.ExecutablePath.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)
}
$launcherIds = @($launchers | ForEach-Object { $_.ProcessId })
$children = $all | Where-Object {
    $_.ProcessId -ne $self -and $launcherIds -contains $_.ParentProcessId -and $_.CommandLine -match $flowCmd
}
$packaged = $all | Where-Object { $_.ProcessId -ne $self -and $_.Name -eq 'FlowLocal.exe' }

$stopped = @($launchers) + @($children) + @($packaged)
$stopped | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# A forced stop during a recording would leave other programs muted: put their sound back.
if ($stopped.Count -gt 0) {
    $python = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path $python) { & $python -m flow restore-sounds *> $null }
}
