$ErrorActionPreference = 'Stop'

try {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run-local-stack.ps1')
  if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "로컬 스택 실행에 실패했습니다. 종료 코드: $LASTEXITCODE" }
  Start-Process 'http://127.0.0.1:5173'
} catch {
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show($_.Exception.Message, 'Main Agent 실행 오류', 'OK', 'Error') | Out-Null
  exit 1
}
