# RESQ Dev — Docker Sandbox Build & Smoke-Test Script
# Usage: powershell -ExecutionPolicy Bypass -File docker/build_sandbox.ps1

$ErrorActionPreference = "Stop"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " RESQ Dev -- Building Execution Sandbox Image     " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Verify Docker Engine Availability
Write-Host ""
Write-Host "[1/3] Checking Docker daemon status..." -ForegroundColor Yellow
try {
    $dockerVersion = docker info --format "{{.ServerVersion}}" 2>$null
    if (-not $dockerVersion) {
        throw "Docker returned empty server version."
    }
    Write-Host "  [OK] Docker Engine is running (Version: $dockerVersion)" -ForegroundColor Green
} catch {
    Write-Host "CRITICAL: Docker Desktop daemon is not running or unreachable." -ForegroundColor Red
    Write-Host "Please ensure Docker Desktop is started and configured for Linux containers." -ForegroundColor Red
    exit 1
}

# 2. Build the Docker Image
$imageTag = "resq-sandbox:latest"
$dockerfilePath = Join-Path $PSScriptRoot "Dockerfile.sandbox"

Write-Host ""
Write-Host "[2/3] Building image '$imageTag' from $dockerfilePath..." -ForegroundColor Yellow
docker build -t $imageTag -f $dockerfilePath $PSScriptRoot

if ($LASTEXITCODE -ne 0) {
    Write-Host "CRITICAL: Docker build failed with exit code $LASTEXITCODE." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "  [OK] Docker image '$imageTag' built successfully." -ForegroundColor Green

# 3. Smoke Test the Image with Sandboxing Flags
Write-Host ""
Write-Host "[3/3] Running sandboxed smoke test: --network none, UID 10001..." -ForegroundColor Yellow
$smokeOutput = docker run --rm --network none $imageTag pytest --version

if ($LASTEXITCODE -ne 0) {
    Write-Host "CRITICAL: Smoke test inside sandbox failed with exit code $LASTEXITCODE." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "  [OK] Sandbox Smoke Test Passed: $smokeOutput" -ForegroundColor Green
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " RESQ Dev Sandbox Ready: $imageTag                " -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
