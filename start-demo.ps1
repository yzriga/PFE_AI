$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

function Test-Command($name) {
  return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command "docker")) {
  throw "Docker is not installed or not on PATH."
}

Write-Host "Starting Scientific Navigator demo stack..." -ForegroundColor Cyan
docker compose up -d --build

Write-Host "Waiting for backend..." -ForegroundColor Cyan
$backendReady = $false
for ($i = 0; $i -lt 60; $i++) {
  try {
    Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/api/sessions/" | Out-Null
    $backendReady = $true
    break
  } catch {
    Start-Sleep -Seconds 2
  }
}

if (-not $backendReady) {
  Write-Warning "Backend did not become ready within the expected time."
}

Write-Host ""
Write-Host "Scientific Navigator is starting." -ForegroundColor Green
Write-Host "Frontend: http://localhost:3000"
Write-Host "Backend:  http://localhost:8000"
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Cyan
Write-Host "  docker compose ps"
Write-Host "  docker compose logs -f backend"
Write-Host "  docker compose logs -f backend-worker"
Write-Host "  .\stop-demo.ps1"
