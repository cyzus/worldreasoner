# WorldReasoner Graph Visualization Startup Script
# Starts both backend and frontend in separate terminal windows

Write-Host "Starting WorldReasoner Graph Visualization..." -ForegroundColor Cyan

# Check if backend dependencies are installed
Write-Host "`nChecking backend dependencies..." -ForegroundColor Yellow
try {
    uv sync
    Write-Host "Backend dependencies OK" -ForegroundColor Green
} catch {
    Write-Host "Failed to install backend dependencies" -ForegroundColor Red
    exit 1
}

# Check if frontend dependencies are installed
Write-Host "`nChecking frontend dependencies..." -ForegroundColor Yellow
if (!(Test-Path "frontend\node_modules")) {
    Write-Host "Installing frontend dependencies (first time only)..." -ForegroundColor Yellow
    Set-Location frontend
    npm install
    Set-Location ..
    Write-Host "Frontend dependencies installed" -ForegroundColor Green
} else {
    Write-Host "Frontend dependencies OK" -ForegroundColor Green
}

# Start backend in new window
Write-Host "`nStarting backend server..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "uv run worldreasoner --reload"

# Wait a moment for backend to start
Start-Sleep -Seconds 2

# Start frontend in new window
Write-Host "Starting frontend dev server..." -ForegroundColor Yellow
Set-Location frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "npm run dev"
Set-Location ..

Write-Host "`n=== WorldReasoner Graph Visualization Started ===" -ForegroundColor Green
Write-Host "Backend API: http://localhost:8018" -ForegroundColor Cyan
Write-Host "API Docs:    http://localhost:8018/docs" -ForegroundColor Cyan
Write-Host "Frontend:    http://localhost:3000" -ForegroundColor Cyan
Write-Host "`nTwo terminal windows have been opened." -ForegroundColor Yellow
Write-Host "Close them to stop the servers." -ForegroundColor Yellow
Write-Host "`nPress any key to exit this window..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
