# Pack the Tasky backend for the EC2 server (run on Windows, in PowerShell):
#
#   powershell -ExecutionPolicy Bypass -File deploy\package.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\package.ps1 -Server 13.201.45.7 -Key C:\keys\tasky.pem
#
# Creates tasky-backend.tar.gz in the repository root with only what the server needs:
# backend/ (code, Dockerfile, migrations), deploy/ and docker-compose.ec2.yml.
# Never included: .env files, the virtualenv, caches, local attachments, tests.
# With -Server and -Key it also uploads the archive and unpacks it into ~/tasky.
param(
    [string]$Server = "",
    [string]$Key = "",
    [string]$User = "ubuntu"
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$archive = Join-Path $root "tasky-backend.tar.gz"

# Windows' built-in tar (bsdtar): exclude patterns match any path component.
$excludes = @(
    ".env", ".env.*", ".venv", "__pycache__", "*.pyc", ".mypy_cache", ".ruff_cache",
    ".pytest_cache", ".coverage", "htmlcov", ".data", "tests", "evals", "*.egg-info"
)
$tarArgs = @("-czf", $archive)
foreach ($pattern in $excludes) { $tarArgs += "--exclude=$pattern" }
# The production template is the one .env-like file the server needs.
$tarArgs += @("backend", "deploy", "docker-compose.ec2.yml")
& "$env:SystemRoot\System32\tar.exe" @tarArgs
if ($LASTEXITCODE -ne 0) { throw "tar failed" }

# deploy/.env.production.example is excluded by the ".env.*" rule: add it back.
$staging = Join-Path $env:TEMP "tasky-pack"
Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Join-Path $staging "deploy") | Out-Null
Copy-Item (Join-Path $root "deploy\.env.production.example") (Join-Path $staging "deploy\")
& "$env:SystemRoot\System32\tar.exe" -xzf $archive -C $staging
& "$env:SystemRoot\System32\tar.exe" -czf $archive -C $staging backend deploy docker-compose.ec2.yml
Remove-Item -Recurse -Force $staging

$sizeMb = [math]::Round((Get-Item $archive).Length / 1MB, 2)
Write-Host "Packed $archive ($sizeMb MB)"

if ($Server -and $Key) {
    Write-Host "Uploading to $User@$Server ..."
    scp -i $Key $archive "${User}@${Server}:~/tasky-backend.tar.gz"
    if ($LASTEXITCODE -ne 0) { throw "scp failed" }
    ssh -i $Key "${User}@${Server}" "mkdir -p ~/tasky && tar -xzf ~/tasky-backend.tar.gz -C ~/tasky && rm ~/tasky-backend.tar.gz && ls ~/tasky"
    if ($LASTEXITCODE -ne 0) { throw "unpacking on the server failed" }
    Write-Host "Uploaded. Next on the server: cd ~/tasky && bash deploy/deploy.sh"
} else {
    Write-Host "Upload it with: scp -i <key.pem> tasky-backend.tar.gz ubuntu@<elastic-ip>:~/"
}
