# Argos - instalador de un solo comando (Windows / PowerShell).
# Idempotente. Uso:
#   powershell -ExecutionPolicy Bypass -File instalar.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Join-Path $ScriptDir "argos"
$VenvDir = if ($env:ARGOS_VENV) { $env:ARGOS_VENV } else { Join-Path $env:USERPROFILE ".argos\venv" }
$Py = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "== Argos: instalando =="

# 1) Python >= 3.11
function Test-PythonVersion {
    param([string]$Exe, [string[]]$Args)
    try {
        & $Exe $Args -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

$PyCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    if (Test-PythonVersion "python" @()) { $PyCmd = "python" }
}
if (-not $PyCmd -and (Get-Command py -ErrorAction SilentlyContinue)) {
    if (Test-PythonVersion "py" @("-3")) { $PyCmd = "py"; $PyArgs = @("-3") }
}
if (-not $PyCmd) {
    Write-Error "Se necesita Python 3.11 o superior: https://www.python.org/downloads/"
    exit 2
}
Write-Host "Python: $PyCmd"

# 2) Virtualenv + instalar
if (-not (Test-Path $Py)) {
    if ($PyCmd -eq "py") { & py -3 -m venv $VenvDir } else { & python -m venv $VenvDir }
}
& $Py -m pip install --quiet --upgrade pip
& $Py -m pip install --quiet $ProjectDir

# 3) Navegador de Playwright
& $Py -m playwright install chromium

# 4) Cookies incluidas en el zip (opcional; para VPS sin navegador)
$ArgosExe = Join-Path $VenvDir "Scripts\argos.exe"
$CookieDir = Join-Path $ScriptDir "cookies"
$Imported = @()
if (Test-Path $CookieDir) {
    $ig = Join-Path $CookieDir "instagram-cookies.json"
    $fb = Join-Path $CookieDir "facebook-cookies.json"
    if (Test-Path $ig) {
        Get-Content $ig -Raw | & $ArgosExe configure ig-cookies --stdin
        $Imported += "instagram"
    }
    if (Test-Path $fb) {
        Get-Content $fb -Raw | & $ArgosExe configure fb-cookies --stdin
        $Imported += "facebook"
    }
    if ($Imported.Count -gt 0) {
        Write-Host "Cookies importadas: $($Imported -join ', ')"
    }
}

# 5) Verificacion
Write-Host "== Verificando =="
& $ArgosExe --version
& $ArgosExe quota

Write-Host ""
Write-Host "== Instalacion completa =="
Write-Host "Binario: $ArgosExe"
Write-Host ""
if ($Imported.Count -gt 0) {
    Write-Host "Sesion lista (cookies importadas)."
    Write-Host "Verifica con: argos doctor"
} else {
    Write-Host "Pendiente (requiere humano): iniciar sesion una vez por red."
    Write-Host "  argos login instagram"
    Write-Host "  argos login facebook"
}
