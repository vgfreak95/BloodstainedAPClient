<#
.SYNOPSIS
Runs the full release build pipeline (see RELEASING.md).

.DESCRIPTION
Sets up .venv with Python 3.13+ and the AP base and True Randomizer requirements,
then runs the build scripts in order:
  1. generate_base_pak.py      (skipped when output\TrueRandomizer-AP-raw.pak exists)
  2. build_ap_base.py          (only with -ApBase; build_static_pak runs it itself)
  3. build_static_pak.py --force [--pin]
  4. build_mod.py [--clean]
  5. build_release.py
Every script still takes its arguments from build_config.toml.

.PARAMETER Python
Python 3.13+ interpreter used to create .venv. Defaults to the first suitable
one among python, python3 and the py launcher.

.PARAMETER RecreateVenv
Delete and recreate .venv, e.g. after it was made with an older Python.

.PARAMETER RebuildBaseline
Regenerate output\TrueRandomizer-AP-raw.pak even if it already exists.

.PARAMETER ApBase
Also run the standalone AP base build. Its output directory must not exist yet.

.PARAMETER Pin
Pin the built static pak in release\static_pak_manifest.json. Only use this
after the candidate has been reviewed (see STATIC_PAK.md).

.PARAMETER Clean
Full rebuild of the ASI instead of an incremental one.

.PARAMETER SkipRelease
Stop after building the ASI instead of packaging the release zip.
#>
[CmdletBinding()]
param(
    [string]$Python,
    [switch]$RecreateVenv,
    [switch]$RebuildBaseline,
    [switch]$ApBase,
    [switch]$Pin,
    [switch]$Clean,
    [switch]$SkipRelease
)

$ErrorActionPreference = 'Stop'
$MinimumPython = [version]'3.13'
$Venv = Join-Path $PSScriptRoot '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Requirements = @(
    (Join-Path $PSScriptRoot 'requirements-ap-base.txt'),
    (Join-Path $PSScriptRoot 'True-Randomization\_requirements.txt')
)
$RequirementsStamp = Join-Path $Venv '.requirements.sha256'
$BaselinePak = Join-Path $PSScriptRoot 'output\TrueRandomizer-AP-raw.pak'

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

# Runs a native command and stops the pipeline when it fails.
function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "'$Command $($Arguments -join ' ')' failed with exit code $LASTEXITCODE"
    }
}

# Returns the interpreter's version, or $null when it can't be run.
function Get-PythonVersion([string]$Command, [string[]]$Arguments = @()) {
    try {
        # No quotes in the code: PowerShell 5.1 and 7 escape them differently for native commands.
        $output = & $Command @Arguments -c 'import sys; print(*sys.version_info[:3], sep=chr(46))' 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) { return [version]($output | Select-Object -Last 1).Trim() }
    } catch {}
    return $null
}

function Find-Python {
    if ($Python) {
        $candidates = @(, @($Python))
    } else {
        $candidates = @(@('python'), @('python3'), @('py', '-3'))
    }
    foreach ($candidate in $candidates) {
        $command = $candidate[0]
        $arguments = @($candidate | Select-Object -Skip 1)
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { continue }
        $version = Get-PythonVersion $command $arguments
        if ($version -and $version -ge $MinimumPython) {
            Write-Host "Using $($candidate -join ' ') (Python $version)"
            return , $candidate
        }
        if ($version) { Write-Host "Skipping $($candidate -join ' '): Python $version is older than $MinimumPython" }
    }
    throw "Python $MinimumPython or newer is required. Install it from https://www.python.org/downloads/ or pass -Python <path>."
}

function Get-RequirementsHash {
    $text = ($Requirements | ForEach-Object { Get-Content -Raw $_ }) -join "`n"
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($text))
        return ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
    } finally {
        $sha.Dispose()
    }
}

function Initialize-Venv {
    Write-Step 'Python environment'
    foreach ($file in $Requirements) {
        if (-not (Test-Path $file)) { throw "Missing requirements file: $file (is the True-Randomization submodule checked out?)" }
    }

    if ((Test-Path $Venv) -and $RecreateVenv) {
        Write-Host "Removing $Venv"
        Remove-Item -Recurse -Force $Venv
    }
    if (Test-Path $VenvPython) {
        $version = Get-PythonVersion $VenvPython
        if (-not $version -or $version -lt $MinimumPython) {
            throw "$Venv uses Python $version, but $MinimumPython+ is required. Rerun with -RecreateVenv."
        }
        Write-Host "Using existing .venv (Python $version)"
    } else {
        $interpreter = Find-Python
        Write-Host "Creating $Venv"
        Invoke-Checked $interpreter[0] (@($interpreter | Select-Object -Skip 1) + @('-m', 'venv', $Venv))
    }

    # Environments created by uv have no pip. PowerShell 5.1 turns redirected native stderr
    # into error records, which would be terminating under 'Stop', so relax it for the probe.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $VenvPython -m pip --version *> $null
        $hasPip = $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if (-not $hasPip) {
        Invoke-Checked $VenvPython @('-m', 'ensurepip', '--upgrade')
    }

    $hash = Get-RequirementsHash
    if ((Test-Path $RequirementsStamp) -and (Get-Content -Raw $RequirementsStamp).Trim() -eq $hash) {
        Write-Host 'Requirements are up to date'
        return
    }
    $installArguments = @('-m', 'pip', 'install', '--disable-pip-version-check')
    foreach ($file in $Requirements) { $installArguments += @('-r', $file) }
    Invoke-Checked $VenvPython $installArguments
    Set-Content -Path $RequirementsStamp -Value $hash -Encoding ascii
}

Push-Location $PSScriptRoot
try {
    Initialize-Venv

    if ($RebuildBaseline -or -not (Test-Path $BaselinePak)) {
        Write-Step 'Generating the raw True Randomizer baseline pak'
        Invoke-Checked $VenvPython @((Join-Path $PSScriptRoot 'generate_base_pak.py'))
    } else {
        Write-Step "Baseline pak exists, skipping generation (pass -RebuildBaseline to regenerate)"
    }

    if ($ApBase) {
        Write-Step 'Building the standalone AP base'
        Invoke-Checked $VenvPython @((Join-Path $PSScriptRoot 'build_ap_base.py'))
    }

    Write-Step 'Building the static pak'
    $staticPakArguments = @((Join-Path $PSScriptRoot 'build_static_pak.py'), '--force')
    if ($Pin) { $staticPakArguments += '--pin' }
    Invoke-Checked $VenvPython $staticPakArguments

    Write-Step 'Building and installing the ASI'
    $modArguments = @((Join-Path $PSScriptRoot 'build_mod.py'))
    if ($Clean) { $modArguments += '--clean' }
    Invoke-Checked $VenvPython $modArguments

    if (-not $SkipRelease) {
        Write-Step 'Packaging the release bundle'
        Invoke-Checked $VenvPython @((Join-Path $PSScriptRoot 'build_release.py'))
    }

    Write-Step 'Pipeline finished'
} finally {
    Pop-Location
}
