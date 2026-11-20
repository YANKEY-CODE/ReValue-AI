#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProjectPath,
    [switch]$Launch
)

$ErrorActionPreference = 'Stop'
$repoUrl = 'https://github.com/YANKEY-CODE/ReValue-AI.git'
$branch = 'fyp1-development'
$pythonProbe = 'import platform, struct, sys; print(sys.version_info[:2] == (3, 12) and struct.calcsize(''P'') == 8 and platform.machine().lower() in (''amd64'', ''x86_64''))'

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments, [string]$Failure)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Failure (exit code $LASTEXITCODE)."
    }
}

function Test-Python312 {
    param([string]$Executable, [string[]]$Selector = @())
    $ErrorActionPreference = 'SilentlyContinue'
    $result = & $Executable @Selector -c $pythonProbe 2>$null
    return ($LASTEXITCODE -eq 0 -and $result -ceq 'True')
}

try {
    $git = Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $launcher = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $standalone = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $python = $null
    $selector = @()
    if ($launcher -and (Test-Python312 -Executable $launcher.Source -Selector @('-3.12'))) {
        $python = $launcher.Source
        $selector = @('-3.12')
    } elseif ($standalone -and $standalone.Source -notlike '*\Microsoft\WindowsApps\python.exe' -and
              (Test-Python312 -Executable $standalone.Source)) {
        $python = $standalone.Source
    }

    if (-not $git) {
        Write-Host 'Install Git for Windows with winget install --exact --id Git.Git'
        Write-Host 'Git installer https://git-scm.com/download/win'
    }
    if (-not $python) {
        Write-Host 'Install Python 3.12 x64 with winget install --exact --id Python.Python.3.12 --architecture x64'
        Write-Host 'Python installers https://www.python.org/downloads/windows/'
    }
    if (-not $git -or -not $python) {
        throw 'Install the missing prerequisite(s), then open a new PowerShell window and rerun this script.'
    }

    if (-not $ProjectPath) {
        $ProjectPath = if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.git')) {
            $PSScriptRoot
        } else {
            Join-Path $env:USERPROFILE 'ReValue-AI'
        }
    }
    $ProjectPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ProjectPath)
    $gitExe = $git.Source

    if (Test-Path -LiteralPath (Join-Path $ProjectPath '.git')) {
        $here = @('-C', $ProjectPath)
        $origin = & $gitExe @here config --get remote.origin.url
        if ($LASTEXITCODE -ne 0 -or $origin -notmatch '^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)YANKEY-CODE/ReValue-AI(\.git)?/?$') {
            throw 'This checkout has a different origin. Use -ProjectPath with a new folder for YANKEY-CODE/ReValue-AI.'
        }
        $changes = & $gitExe @here status --porcelain
        if ($LASTEXITCODE -ne 0) { throw 'Could not read the checkout status.' }
        if ($changes) { throw 'This checkout has uncommitted changes. Save your work first, or use -ProjectPath with a new folder.' }

        Write-Host "Updating $branch in $ProjectPath"
        Invoke-Checked $gitExe ($here + @('fetch', 'origin', $branch)) 'Could not fetch the ReValue branch from GitHub'
        $localBranch = & $gitExe @here for-each-ref '--format=%(refname)' "refs/heads/$branch"
        if ($LASTEXITCODE -ne 0) { throw 'Could not read local branch information.' }
        if ($localBranch -contains "refs/heads/$branch") {
            Invoke-Checked $gitExe ($here + @('switch', $branch)) 'Could not switch to the ReValue development branch'
        } else {
            Invoke-Checked $gitExe ($here + @('switch', '--create', $branch, 'FETCH_HEAD')) 'Could not create the ReValue development branch'
        }
        Invoke-Checked $gitExe ($here + @('merge', '--ff-only', 'FETCH_HEAD')) 'Could not fast-forward. Use -ProjectPath with a new folder if this branch has diverged'
    } else {
        if ((Test-Path -LiteralPath $ProjectPath) -and
            ((-not (Test-Path -LiteralPath $ProjectPath -PathType Container)) -or (Get-ChildItem -LiteralPath $ProjectPath -Force | Select-Object -First 1))) {
            throw 'The destination exists and is not an empty folder. Choose a new folder with -ProjectPath.'
        }
        Write-Host "Cloning $branch into $ProjectPath"
        Invoke-Checked $gitExe @('clone', '--branch', $branch, '--single-branch', '--', $repoUrl, $ProjectPath) 'Could not clone the ReValue branch from GitHub'
    }

    $checkpoint = Join-Path $ProjectPath 'backend\models\revalue_exterior_yolo11n_v0.2.pt'
    $requirements = Join-Path $ProjectPath 'backend\requirements-windows-cpu.txt'
    $startScript = Join-Path $ProjectPath 'start-revalue.ps1'
    foreach ($required in @($checkpoint, $requirements, $startScript)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required file missing: $required. Use a complete checkout of $branch."
        }
    }

    $venv = Join-Path $ProjectPath '.venv'
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venv)) {
        Write-Host 'Creating the Python 3.12 virtual environment'
        Invoke-Checked $python ($selector + @('-m', 'venv', $venv)) 'Could not create the virtual environment'
    }
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf) -or -not (Test-Python312 -Executable $venvPython)) {
        throw "The environment at $venv cannot run Python 3.12 x64. Move that .venv folder outside the checkout and run setup again."
    }

    $pytorchPins = @(Get-Content -LiteralPath $requirements | Where-Object { $_ -match '^torch(vision)?==\S+\+cpu$' })
    if ($pytorchPins.Count -ne 2) { throw 'The Windows requirements are missing the two PyTorch CPU pins.' }
    Write-Host 'Installing the PyTorch and Torchvision CPU wheels'
    Invoke-Checked $venvPython (@('-m', 'pip', 'install', '--no-deps', '--only-binary=:all:', '--index-url', 'https://download.pytorch.org/whl/cpu') + $pytorchPins) 'PyTorch installation failed. Check connectivity to download.pytorch.org and download-r2.pytorch.org'

    Write-Host 'Installing backend dependencies'
    Invoke-Checked $venvPython @('-m', 'pip', 'install', '--only-binary=:all:', '--index-url', 'https://pypi.org/simple', '-r', $requirements) 'Backend installation failed. Check connectivity to PyPI and see WINDOWS_SETUP.md'
    Invoke-Checked $venvPython @('-m', 'pip', 'check') 'Installed dependencies are inconsistent'
    & $startScript -Check

    Write-Host "Setup complete. ReValue AI is installed in $ProjectPath"
    if ($Launch) {
        & $startScript
    } else {
        Write-Host ('To start ReValue AI, run & ''{0}''' -f $startScript.Replace("'", "''"))
    }
} catch {
    throw "ReValue Windows setup failed. $($_.Exception.Message)"
}
