# Build CRE Underwriting for Windows (x64). Windows PowerShell 5.1 or PowerShell 7.
#
# Prerequisites (one-time):
#   winget install Python.Python.3.12 OpenJS.NodeJS.LTS
#   py -3.12 -m venv desktop\.venv
#   desktop\.venv\Scripts\python -m pip install -r backend\requirements.txt -r desktop\requirements.txt
#   Optional, for the installer: winget install JRSoftware.InnoSetup
#
# Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1
#
# Output (desktop\dist\):
#   CRE Underwriting\CRE Underwriting.exe        the app folder
#   CRE-Underwriting-windows-portable.zip        unzip anywhere and run
#   CRE-Underwriting-Setup-<version>.exe         installer (when Inno Setup is installed)
#
# Switches:
#   -SkipFrontend       reuse the existing frontend\dist (no npm ci / npm run build)
#   -SkipTests          skip the desktop shell tests
#   -RequireInstaller   fail (instead of skipping) when Inno Setup isn't installed (CI)
param(
    [switch]$SkipFrontend,
    [switch]$SkipTests,
    [switch]$RequireInstaller
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Desktop = Join-Path $Repo 'desktop'
$VenvPy = Join-Path $Desktop '.venv\Scripts\python.exe'
$Dist = Join-Path $Desktop 'dist'
$Work = Join-Path $Desktop 'build'
$AppDir = Join-Path $Dist 'CRE Underwriting'
$AppExe = Join-Path $AppDir 'CRE Underwriting.exe'
$PortableZip = Join-Path $Dist 'CRE-Underwriting-windows-portable.zip'

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

# Native tools report failure through their exit code. Run them with
# ErrorActionPreference=Continue so a line on stderr (npm, PyInstaller) is not
# mistaken for a failure by Windows PowerShell 5.1, then check the code.
function Invoke-Native([string]$What, [scriptblock]$Command) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Command
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $saved
    }
    if ($code -ne 0) {
        throw "$What failed (exit code $code)."
    }
}

if (-not (Test-Path $VenvPy)) {
    Write-Host 'Missing desktop\.venv - see the prerequisites at the top of this script.' -ForegroundColor Red
    exit 1
}

$VersionLine = Select-String -Path (Join-Path $Desktop 'cre_desktop\version.py') -Pattern '^VERSION = "([^"]+)"'
if (-not $VersionLine) { throw 'VERSION not found in desktop\cre_desktop\version.py' }
$Version = $VersionLine.Matches[0].Groups[1].Value
Write-Host "CRE Underwriting $Version (Windows build)"

if (-not $SkipTests) {
    Write-Step 'Desktop shell tests'
    Invoke-Native 'Desktop shell tests' { & $VenvPy -m pytest (Join-Path $Desktop 'tests') -q -p no:cacheprovider }
}

if (-not $SkipFrontend) {
    Write-Step 'Building frontend'
    Push-Location (Join-Path $Repo 'frontend')
    try {
        Invoke-Native 'npm ci' { & npm ci --no-audit --no-fund }
        Invoke-Native 'npm run build' { & npm run build }
    } finally {
        Pop-Location
    }
} elseif (-not (Test-Path (Join-Path $Repo 'frontend\dist\index.html'))) {
    throw 'frontend\dist is missing - run without -SkipFrontend (or npm run build in frontend\).'
}

$Icon = Join-Path $Desktop 'assets\AppIcon.ico'
if (-not (Test-Path $Icon)) {
    Write-Step 'Generating the Windows icon'
    Invoke-Native 'Icon generation' { & $VenvPy (Join-Path $Desktop 'assets\make_icon.py') --ico }
}

Write-Step 'Building the app folder (PyInstaller)'
Invoke-Native 'PyInstaller' {
    & $VenvPy -m PyInstaller --noconfirm --clean --log-level WARN `
        --distpath $Dist --workpath $Work (Join-Path $Desktop 'cre_underwriting.spec')
}
if (-not (Test-Path $AppExe)) { throw "PyInstaller finished but $AppExe is missing." }

Write-Step 'Self-test of the built app (frozen dependencies, no window)'
# The exe is a windowed app, so it runs detached from this console: capture
# its output through files and wait for it explicitly.
$SelfTestOut = Join-Path $Work 'selftest-stdout.txt'
$SelfTestErr = Join-Path $Work 'selftest-stderr.txt'
$proc = Start-Process -FilePath $AppExe -ArgumentList '--self-test' -Wait -PassThru -NoNewWindow `
    -RedirectStandardOutput $SelfTestOut -RedirectStandardError $SelfTestErr
Get-Content $SelfTestOut | Write-Host
if ((Get-Item $SelfTestErr).Length -gt 0) { Get-Content $SelfTestErr | Write-Host }
if ($proc.ExitCode -ne 0) { throw "Self-test failed (exit code $($proc.ExitCode))." }

Write-Step 'Packaging the portable zip'
if (Test-Path $PortableZip) { Remove-Item $PortableZip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $AppDir, $PortableZip, [System.IO.Compression.CompressionLevel]::Optimal, $true)

Write-Step 'Building the installer (Inno Setup)'
$Iscc = $null
$candidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
)
foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path $candidate)) { $Iscc = $candidate; break }
}
if (-not $Iscc) {
    $onPath = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($onPath) { $Iscc = $onPath.Source }
}
$Installer = Join-Path $Dist "CRE-Underwriting-Setup-$Version.exe"
if ($Iscc) {
    Invoke-Native 'Inno Setup compile' {
        & $Iscc /Q "/DAppVersion=$Version" "/DAppSourceDir=$AppDir" "/DOutputDir=$Dist" `
            (Join-Path $Desktop 'windows\installer.iss')
    }
    if (-not (Test-Path $Installer)) { throw "Inno Setup finished but $Installer is missing." }
} elseif ($RequireInstaller) {
    throw 'Inno Setup 6 (ISCC.exe) not found.'
} else {
    Write-Host 'Inno Setup 6 not found - skipping the installer. To build it, install Inno Setup 6'
    Write-Host '(winget install JRSoftware.InnoSetup, or https://jrsoftware.org/isdl.php) and run this script again.'
    $Installer = $null
}

$appMb = [math]::Round(((Get-ChildItem $AppDir -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB), 0)
$zipMb = [math]::Round(((Get-Item $PortableZip).Length / 1MB), 0)
Write-Host ''
Write-Host "Built: $AppExe ($appMb MB)"
Write-Host "       $PortableZip ($zipMb MB)"
if ($Installer) {
    $setupMb = [math]::Round(((Get-Item $Installer).Length / 1MB), 0)
    Write-Host "       $Installer ($setupMb MB)"
}
