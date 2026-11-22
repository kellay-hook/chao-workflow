$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    Write-Host "== Backend tests ==" -ForegroundColor Cyan
    .\.venv\Scripts\python -m pytest backend/tests -q
    Write-Host "== Backend lint ==" -ForegroundColor Cyan
    .\.venv\Scripts\ruff check backend/app backend/tests backend/scripts

    Push-Location web
    try {
        Write-Host "== Frontend build ==" -ForegroundColor Cyan
        npm run build
        Write-Host "== Playwright E2E ==" -ForegroundColor Cyan
        npm run test:e2e
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}