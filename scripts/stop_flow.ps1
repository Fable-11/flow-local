# Stops a running Flow Local (source install or packaged build). Safe to run when it is not running.
$self = $PID
Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $self -and (
            $_.Name -eq 'FlowLocal.exe' -or
            $_.CommandLine -match '(^|[\s"\\])-m flow(\s|$)'
        )
    } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
