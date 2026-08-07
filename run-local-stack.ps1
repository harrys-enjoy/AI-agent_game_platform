$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectsRoot = Split-Path -Parent $workspaceRoot
$catalogRoot = Join-Path $projectsRoot 'Catalog & Manual(Game project)'
$backendRoot = Join-Path $workspaceRoot 'backend'
$frontendRoot = Join-Path $workspaceRoot 'frontend'

function Test-Port($port) {
  return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

if (-not (Test-Port 3010)) {
  $env:PORT = '3010'
  $env:AGENT_PUBLIC_URL = 'http://127.0.0.1:3010'
  Start-Process -FilePath 'node.exe' -ArgumentList 'src/server.js' -WorkingDirectory $catalogRoot -WindowStyle Hidden | Out-Null
}

if (-not (Test-Port 8000)) {
  $env:LIVE_AGENT_DISCOVERY = 'true'
  $env:GAME_QA_AGENT_URL = 'http://127.0.0.1:3010/message:send'
  Start-Process -FilePath 'C:\Anaconda3\python.exe' -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' -WorkingDirectory $backendRoot -WindowStyle Hidden | Out-Null
}

if (-not (Test-Port 5173)) {
  Start-Process -FilePath 'npm.cmd' -ArgumentList 'run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173' -WorkingDirectory $frontendRoot -WindowStyle Hidden | Out-Null
}

for ($i = 0; $i -lt 30; $i++) {
  try {
    $cat = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:3010/health' -TimeoutSec 2
    $main = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/health' -TimeoutSec 2
    $ui = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5173' -TimeoutSec 2
    if ($cat.StatusCode -eq 200 -and $main.StatusCode -eq 200 -and $ui.StatusCode -eq 200) { break }
  } catch {
    Start-Sleep -Milliseconds 500
  }
  if ($i -eq 29) { throw 'CAT, Main, or UI did not become healthy.' }
}

$agents = Invoke-RestMethod 'http://127.0.0.1:8000/api/agents'
$requestBody = @{ content = 'Tell me about the game lore' } | ConvertTo-Json -Compress
$reply = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/chats/Game%20Q%26A/reply' -Method Post -ContentType 'application/json' -Body $requestBody

[pscustomobject]@{
  cat = 'http://127.0.0.1:3010/health -> 200'
  main = 'http://127.0.0.1:8000/health -> 200'
  ui = 'http://127.0.0.1:5173 -> 200'
  agents = ($agents | ConvertTo-Json -Compress)
  reply = ($reply | ConvertTo-Json -Compress)
} | ConvertTo-Json
