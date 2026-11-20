#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$HoudanWeights,
    [ValidateRange(1, 65535)][int]$Port = 8766,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The ReValue virtual environment is missing. Run setup-windows.ps1 first.'
}

$arguments = @('-u', '-m', 'fyp.model_comparison', '--port', [string]$Port)
if ($HoudanWeights) {
    $arguments += @('--houdan-weights', $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($HoudanWeights))
}
if ($NoBrowser) {
    $arguments += '--no-browser'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Model comparison exited with code $LASTEXITCODE. See the error above and fyp/MODEL_COMPARISON.md."
    }
} finally {
    Pop-Location
}
