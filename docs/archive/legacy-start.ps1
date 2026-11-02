$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BackendPort = 8000
$BackendUrl = "http://127.0.0.1:$BackendPort"
$HealthUrl = "$BackendUrl/health"
$BackendProcess = $null
$LogDir = Join-Path $Root "logs"
$StartupLog = Join-Path $LogDir "startup.log"
$BackendOutLog = Join-Path $LogDir "backend.out.log"
$BackendErrLog = Join-Path $LogDir "backend.err.log"
$VenvDir = Join-Path $Root ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$RequirementsFile = Join-Path $Root "requirements.txt"
$RequirementsMarker = Join-Path $VenvDir ".requirements_installed"
$ElectronDir = Join-Path $Root "electron_client"
$NpmMarker = Join-Path $ElectronDir "node_modules\.npm_installed"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

try {
    Start-Transcript -Path $StartupLog -Append | Out-Null
} catch {
    Write-Host "Warning: cannot start transcript: $($_.Exception.Message)"
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory = $Root
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($ArgumentList -join ' ')"
        }
    } finally {
        Pop-Location
    }
}

function Find-SystemPython {
    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($version in @("3.12", "3.11", "3.10")) {
            if (Test-PythonCandidate -FilePath $pyLauncher.Source -ArgumentList @("-$version")) {
                return @{
                    FilePath = $pyLauncher.Source
                    Args = @("-$version")
                    Version = $version
                }
            }
        }
    }

    $python = Get-Command "python" -ErrorAction SilentlyContinue
    if ($python -and (Test-PythonCandidate -FilePath $python.Source -ArgumentList @())) {
        $version = Get-PythonVersion -FilePath $python.Source -ArgumentList @()
        return @{
            FilePath = $python.Source
            Args = @()
            Version = $version
        }
    }

    throw "Compatible Python was not found. Please install Python 3.10, 3.11 or 3.12. Python 3.13/3.14 is not recommended because numpy, OCR and vector packages may need local compilation on Windows."
}

function Get-PythonVersion {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )

    try {
        $versionArgs = @($ArgumentList) + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        $output = & $FilePath @versionArgs 2>$null
        return [string]($output | Select-Object -First 1)
    } catch {
        return ""
    }
}

function Test-PythonCandidate {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )

    $version = Get-PythonVersion -FilePath $FilePath -ArgumentList $ArgumentList
    return $version -in @("3.10", "3.11", "3.12")
}

function Get-VenvPythonVersion {
    if (-not (Test-Path $PythonExe)) {
        return ""
    }
    return Get-PythonVersion -FilePath $PythonExe -ArgumentList @()
}

function Remove-ExistingVenv {
    $resolvedRoot = [System.IO.Path]::GetFullPath($Root)
    $resolvedVenv = [System.IO.Path]::GetFullPath($VenvDir)
    if (-not $resolvedVenv.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove venv outside project directory: $resolvedVenv"
    }
    if ((Split-Path -Leaf $resolvedVenv) -ne ".venv") {
        throw "Refusing to remove unexpected venv path: $resolvedVenv"
    }
    if (Test-Path $resolvedVenv) {
        Write-Host "Removing incompatible Python virtual environment: $resolvedVenv"
        Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
    }
}

function Test-MarkerFresh {
    param(
        [string]$MarkerPath,
        [string[]]$SourcePaths
    )

    if (-not (Test-Path $MarkerPath)) {
        return $false
    }

    $markerTime = (Get-Item $MarkerPath).LastWriteTimeUtc
    foreach ($sourcePath in $SourcePaths) {
        if ((Test-Path $sourcePath) -and ((Get-Item $sourcePath).LastWriteTimeUtc -gt $markerTime)) {
            return $false
        }
    }
    return $true
}

function Ensure-PythonEnvironment {
    Write-Step "Preparing Python backend environment"

    if (-not (Test-Path $RequirementsFile)) {
        throw "Cannot find requirements.txt. Root=$Root"
    }

    $venvVersion = Get-VenvPythonVersion
    if ($venvVersion -and ($venvVersion -notin @("3.10", "3.11", "3.12"))) {
        Write-Host "Existing .venv uses Python $venvVersion, which is not supported by this launcher."
        Remove-ExistingVenv
    }

    if (-not (Test-Path $PythonExe)) {
        Write-Host "Creating local Python virtual environment: $VenvDir"
        $pythonLauncher = Find-SystemPython
        Write-Host "Using Python $($pythonLauncher.Version) to create .venv"
        $venvArgs = @($pythonLauncher.Args) + @("-m", "venv", $VenvDir)
        Invoke-Checked -FilePath $pythonLauncher.FilePath -ArgumentList $venvArgs -WorkingDirectory $Root
    }

    if (-not (Test-Path $PythonExe)) {
        throw "Virtual environment was not created successfully: $PythonExe"
    }

    $env:PYTHON = $PythonExe
    Invoke-Checked -FilePath $PythonExe -ArgumentList @("--version") -WorkingDirectory $Root

    $dependenciesReady = Test-MarkerFresh -MarkerPath $RequirementsMarker -SourcePaths @($RequirementsFile)
    if (-not $dependenciesReady) {
        Write-Host "Installing Python dependencies from requirements.txt. First run may take several minutes ..."
        Invoke-Checked -FilePath $PythonExe -ArgumentList @("-m", "pip", "install", "--upgrade", "pip") -WorkingDirectory $Root
        Invoke-Checked -FilePath $PythonExe -ArgumentList @("-m", "pip", "install", "-r", $RequirementsFile) -WorkingDirectory $Root
        New-Item -ItemType File -Path $RequirementsMarker -Force | Out-Null
    } else {
        Write-Host "Python dependencies are already installed."
    }
}

function Ensure-NodeEnvironment {
    Write-Step "Preparing Electron frontend environment"

    $node = Get-Command "node" -ErrorAction SilentlyContinue
    if (-not $node) {
        throw "Node.js was not found. Please install Node.js LTS and add it to PATH."
    }

    $npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if (-not $npm) {
        throw "npm.cmd was not found. Please install Node.js LTS and add it to PATH."
    }

    $packageJson = Join-Path $ElectronDir "package.json"
    $packageLock = Join-Path $ElectronDir "package-lock.json"
    $nodeModules = Join-Path $ElectronDir "node_modules"

    if (-not (Test-Path $packageJson)) {
        throw "Cannot find electron_client\package.json."
    }

    $npmReady = (Test-Path $nodeModules) -and (Test-MarkerFresh -MarkerPath $NpmMarker -SourcePaths @($packageJson, $packageLock))
    if (-not $npmReady) {
        Write-Host "Installing Electron dependencies with npm.cmd install. First run may take several minutes ..."
        Invoke-Checked -FilePath $npm.Source -ArgumentList @("install") -WorkingDirectory $ElectronDir
        New-Item -ItemType File -Path $NpmMarker -Force | Out-Null
    } else {
        Write-Host "Electron dependencies are already installed."
    }
}

function Get-BackendHealth {
    try {
        return Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3
    } catch {
        return $null
    }
}

function Get-PortOwner {
    $connection = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $connection) {
        return $null
    }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)" -ErrorAction SilentlyContinue
}

function Stop-StaleBackendIfNeeded {
    $health = Get-BackendHealth
    if ($health -and $health.status -eq "ok" -and $health.build) {
        Write-Host "Backend already running: $HealthUrl"
        Write-Host "Build: $($health.build)"
        return $true
    }

    $owner = Get-PortOwner
    if (-not $owner) {
        return $false
    }

    $commandLine = [string]$owner.CommandLine
    $isThisBackend = $commandLine.Contains("uvicorn") -and $commandLine.Contains("bid_parser_api:app")
    if ($isThisBackend) {
        Write-Host "Stopping stale backend process PID $($owner.ProcessId) ..."
        Stop-Process -Id $owner.ProcessId -Force
        Start-Sleep -Seconds 1
        return $false
    }

    throw "Port $BackendPort is occupied by another process. PID=$($owner.ProcessId), CommandLine=$commandLine"
}

function Wait-BackendReady {
    param([int]$TimeoutSeconds = 45)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $health = Get-BackendHealth
        if ($health -and $health.status -eq "ok") {
            Write-Host "Backend health check passed: $HealthUrl"
            if ($health.build) {
                Write-Host "Build: $($health.build)"
            }
            return
        }
        Start-Sleep -Milliseconds 700
    }

    throw "Backend startup timed out. Run manually from project root: python -m uvicorn bid_parser_api:app --host 127.0.0.1 --port 8000"
}

try {
    Write-Step "Checking project directory"
    Write-Host "Root: $Root"
    Write-Host "Startup log: $StartupLog"
    Write-Host "Backend stdout log: $BackendOutLog"
    Write-Host "Backend stderr log: $BackendErrLog"
    if (-not (Test-Path (Join-Path $Root "bid_parser_api.py"))) {
        throw "Cannot find bid_parser_api.py. Root=$Root"
    }
    if (-not (Test-Path (Join-Path $Root "electron_client\package.json"))) {
        throw "Cannot find electron_client\package.json."
    }

    Ensure-PythonEnvironment
    Ensure-NodeEnvironment

    Write-Step "Checking backend port"
    $backendAlreadyRunning = Stop-StaleBackendIfNeeded

    if (-not $backendAlreadyRunning) {
        Write-Step "Starting FastAPI backend"
        $startInfo = @{
            FilePath = $PythonExe
            ArgumentList = @("-m", "uvicorn", "bid_parser_api:app", "--host", "127.0.0.1", "--port", [string]$BackendPort)
            WorkingDirectory = $Root
            WindowStyle = "Hidden"
            RedirectStandardOutput = $BackendOutLog
            RedirectStandardError = $BackendErrLog
            PassThru = $true
        }
        $BackendProcess = Start-Process @startInfo

        Wait-BackendReady -TimeoutSeconds 45
    }

    Write-Step "Starting Electron frontend"
    Push-Location $ElectronDir
    try {
        npm.cmd start
    } finally {
        Pop-Location
    }
} catch {
    Write-Host ""
    Write-Host "Startup failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    if ($BackendProcess -and -not $BackendProcess.HasExited) {
        Write-Step "Stopping backend started by this script"
        Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    try {
        Stop-Transcript | Out-Null
    } catch {
    }
}
