#Requires -RunAsAdministrator
<#
  Установка шима как Windows-службы через WinSW (идемпотентно).
  Запускать от администратора:
      PowerShell -ExecutionPolicy Bypass -File .\install-shim-service.ps1

  Что делает:
    1. Создаёт .venv шима (uv sync), если его нет.
    2. Скачивает WinSW как iikona-audit-shim.exe в корень шима (если нет).
    3. Кладёт конфиг рядом с exe и регистрирует+стартует службу.
    4. Проверяет /health.

  Движок rlm ставится ОТДЕЛЬНО (родной установщик upstream) — см. DEPLOY.md, вариант A.
#>
$ErrorActionPreference = "Stop"

# Корень шима = на два уровня выше (deploy/windows -> audit-shim).
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Write-Host "Каталог шима: $Root"

# --- uv ---
$Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $Uv) { $Uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
if (-not (Test-Path $Uv)) {
    throw "uv не найден. Установи: irm https://astral.sh/uv/install.ps1 | iex (uv нужен и для rlm)."
}

# --- 1. .venv ---
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "Создаю .venv (uv sync)..."
    Push-Location $Root
    try { & $Uv sync } finally { Pop-Location }
}

# --- 2. WinSW ---
$Exe = Join-Path $Root "iikona-audit-shim.exe"
if (-not (Test-Path $Exe)) {
    $Url = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe"
    Write-Host "Скачиваю WinSW: $Url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $Exe -UseBasicParsing
}

# --- 3. Конфиг рядом с exe (basename должен совпадать) ---
Copy-Item (Join-Path $PSScriptRoot "iikona-audit-shim.xml") (Join-Path $Root "iikona-audit-shim.xml") -Force
Write-Host "ПРОВЕРЬ блок <env> в $Root\iikona-audit-shim.xml (AUDIT_SRC, AUDIT_HOST) перед прод-запуском."

# --- 4. Установка + старт ---
& $Exe stop   2>$null
& $Exe uninstall 2>$null
& $Exe install
& $Exe start

# --- 5. Health ---
Start-Sleep -Seconds 3
try {
    $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:9001/health" -TimeoutSec 5
    Write-Host "Health: $($r.StatusCode) $($r.Content)"
} catch {
    Write-Warning "Шим не ответил на /health: $_"
    Write-Warning "Логи: $Root\iikona-audit-shim.out.log и .err.log ; статус: $Exe status"
}
