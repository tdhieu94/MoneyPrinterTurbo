# Starts the WebUI as a desktop-style app on Windows: the server runs hidden,
# the UI opens in its own window (Edge or Chrome app mode), and closing that
# window stops the server. Started by the shortcut install_desktop_app.bat makes.
# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts as ANSI.

$ErrorActionPreference = "Stop"
$AppName = "MoneyPrinterTurbo"
$Root = Split-Path -Parent $PSScriptRoot

function Show-Message([string]$Text) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($Text, $AppName) | Out-Null
}

function Find-FreePort {
    foreach ($port in 8501..8599) {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
        try {
            $listener.ExclusiveAddressUse = $true
            $listener.Start()
            $listener.Stop()
            return $port
        } catch {
            try { $listener.Stop() } catch {}
        }
    }
    return $null
}

function Test-Port([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $Port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Find-AppBrowser {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    return $null
}

# One instance only: a second browser launch with the same profile hands off to
# the first one and exits at once, which would stop the new server under it.
$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, "Local\MoneyPrinterTurboDesktopApp", [ref]$createdNew)
if (-not $createdNew) {
    Show-Message "The app is already running. Look for its window on the taskbar."
    exit 0
}

# The work runs in a function so every early return still reaches the finally
# block that stops the server and releases the mutex.
function Start-DesktopApp {
    $server = $null
    try {
        $python = Join-Path $Root ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $python)) {
            $python = Join-Path $Root "lib\python\python.exe"
        }
        if (-not (Test-Path -LiteralPath $python)) {
            Show-Message "Python environment not found. Run install_desktop_app.bat in the project folder first."
            return
        }

        $port = Find-FreePort
        if ($null -eq $port) {
            Show-Message "No free port found between 8501 and 8599."
            return
        }

        $dataDir = Join-Path $env:LOCALAPPDATA "MoneyPrinterTurboDesktop"
        New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
        $outLog = Join-Path $dataDir "server.out.log"
        $errLog = Join-Path $dataDir "server.err.log"

        $env:PYTHONPATH = $Root
        $env:PYTHONUTF8 = "1"
        $serverArgs = @(
            "-m", "streamlit", "run", "webui\Main.py",
            "--server.address=127.0.0.1",
            "--server.port=$port",
            "--server.headless=true",
            "--browser.serverAddress=127.0.0.1",
            "--browser.gatherUsageStats=False",
            "--client.toolbarMode=minimal",
            "--logger.hideWelcomeMessage=True",
            "--server.showEmailPrompt=False"
        )
        $server = Start-Process -FilePath $python -ArgumentList $serverArgs -WorkingDirectory $Root `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog

        $ready = $false
        foreach ($attempt in 1..120) {
            if ($server.HasExited) { break }
            if (Test-Port $port) { $ready = $true; break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $ready) {
            Show-Message "The app did not start. See the log files in: $dataDir"
            return
        }

        $url = "http://127.0.0.1:$port"
        $browser = Find-AppBrowser
        if ($browser) {
            # A dedicated profile keeps this browser process alive until the app
            # window closes, so -Wait returns exactly when the user closes it.
            $profileDir = Join-Path $dataDir "browser-profile"
            $browserArgs = @(
                "--app=$url",
                "--user-data-dir=`"$profileDir`"",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1500,950"
            )
            Start-Process -FilePath $browser -ArgumentList $browserArgs -Wait
        } else {
            Start-Process $url
            Show-Message "The app is open in your browser at $url. Press OK here when you are done to stop it."
        }
    } catch {
        Show-Message ("Failed to start: " + $_.Exception.Message)
        return
    } finally {
        if ($server -and -not $server.HasExited) {
            # /T also stops the worker processes Streamlit and FFmpeg started.
            Start-Process -FilePath "taskkill.exe" -ArgumentList @("/PID", $server.Id, "/T", "/F") `
                -WindowStyle Hidden -Wait
        }
        $mutex.ReleaseMutex()
        $mutex.Dispose()
    }
}

Start-DesktopApp
