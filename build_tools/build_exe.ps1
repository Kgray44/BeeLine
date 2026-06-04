[CmdletBinding()]
param(
    [switch]$NoClean,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $ScriptRoot ".."))
$SpecPath = Join-Path $RepoRoot "BeeLine_Issue_Tracker.spec"
$ExecutablePath = Join-Path $RepoRoot "dist\BeeLine Issue Tracker\BeeLine Issue Tracker.exe"

function Test-IsRepoChild {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )

    $repoFull = (Resolve-Path -LiteralPath $RepoRoot).ProviderPath.TrimEnd("\", "/")
    $resolved = (Resolve-Path -LiteralPath $Path).ProviderPath
    $comparison = [System.StringComparison]::OrdinalIgnoreCase

    return $resolved.Equals($repoFull, $comparison) -or
        $resolved.StartsWith($repoFull + [System.IO.Path]::DirectorySeparatorChar, $comparison) -or
        $resolved.StartsWith($repoFull + [System.IO.Path]::AltDirectorySeparatorChar, $comparison)
}

function Remove-RepoChild {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    $target = Join-Path $RepoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $target)) {
        return
    }
    if (-not (Test-IsRepoChild -Path $target)) {
        throw "Refusing to remove '$target' because it is outside the repository root."
    }
    Remove-Item -LiteralPath $target -Recurse -Force
}

if (-not (Test-Path -LiteralPath $SpecPath)) {
    throw "Missing PyInstaller spec file: $SpecPath"
}

Push-Location $RepoRoot
try {
    $pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python command '$Python' was not found. Install Python or pass -Python with the full path to python.exe."
    }

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Python -c "import PyInstaller" *>$null
        $pyInstallerCheckExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($pyInstallerCheckExitCode -ne 0) {
        throw @"
PyInstaller is not installed for '$Python'.

Install the build requirements, then run this script again:
  $Python -m pip install -r requirements.txt
"@
    }

    if (-not $NoClean) {
        Write-Host "Cleaning previous PyInstaller artifacts..."
        Remove-RepoChild -RelativePath "build"
        Remove-RepoChild -RelativePath "dist"
    }

    $pyInstallerArgs = @("--noconfirm", "BeeLine_Issue_Tracker.spec")
    if (-not $NoClean) {
        $pyInstallerArgs = @("--clean") + $pyInstallerArgs
    }

    Write-Host "Building BeeLine Issue Tracker executable..."
    & $Python -m PyInstaller @pyInstallerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    if (-not (Test-Path -LiteralPath $ExecutablePath)) {
        throw "Build completed but the executable was not found at: $ExecutablePath"
    }

    $resolvedExecutable = (Resolve-Path -LiteralPath $ExecutablePath).ProviderPath
    Write-Host ""
    Write-Host "BeeLine executable created:"
    Write-Host "  $resolvedExecutable"
}
finally {
    Pop-Location
}
