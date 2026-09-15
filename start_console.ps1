param(
  [int]$ApiPort = 8000,
  [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPy = Join-Path (Split-Path -Parent $Project) ".venv\Scripts\python.exe"
$VenvPyw = Join-Path (Split-Path -Parent $Project) ".venv\Scripts\pythonw.exe"
$Py = if (Test-Path $VenvPyw) { $VenvPyw } elseif (Test-Path $VenvPy) { $VenvPy } else { "python" }
$Node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
$Vite = Join-Path $Project "frontend\node_modules\vite\bin\vite.js"
$BackendOut = Join-Path $Project "backend_console_runtime.out.log"
$BackendErr = Join-Path $Project "backend_console_runtime.err.log"
$FrontendOut = Join-Path $Project "frontend_console_runtime.out.log"
$FrontendErr = Join-Path $Project "frontend_console_runtime.err.log"

if (-not $Node -or -not (Test-Path $Vite)) {
  throw "Node/Vite not found. Run npm.cmd install in frontend first."
}

Write-Host "Starting FastAPI on http://127.0.0.1:$ApiPort using $Py"
Start-Process -FilePath $Py -WorkingDirectory $Project -WindowStyle Hidden `
  -ArgumentList @("-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
  -RedirectStandardOutput $BackendOut -RedirectStandardError $BackendErr

Write-Host "Starting React console on http://127.0.0.1:$WebPort"
Start-Process -FilePath $Node -WorkingDirectory (Join-Path $Project "frontend") -WindowStyle Hidden `
  -ArgumentList @($Vite, "--host", "127.0.0.1", "--port", "$WebPort") `
  -RedirectStandardOutput $FrontendOut -RedirectStandardError $FrontendErr

for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep -Milliseconds 500
  $web = Get-NetTCPConnection -LocalPort $WebPort -State Listen -ErrorAction SilentlyContinue
  $api = Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue
  if ($web -and $api) {
    Write-Host "Console ready: http://127.0.0.1:$WebPort/" -ForegroundColor Green
    exit 0
  }
}
throw "Console did not start. Check backend_console_runtime.err.log and frontend_console_runtime.err.log."
