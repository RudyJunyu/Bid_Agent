param([switch]$NoBuild)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $projectRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Install Docker Desktop (Linux containers) or Docker Engine with Compose first.'
    }
    if (-not (Test-Path -LiteralPath '.env')) {
        Copy-Item -LiteralPath '.env.example' -Destination '.env'
        Write-Host 'Created .env. Add LLM / MinerU credentials when using those features.'
    }
    & docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Invalid Compose configuration.' }
    if ($NoBuild) { & docker compose up -d --wait --wait-timeout 180 }
    else { & docker compose up -d --build --wait --wait-timeout 180 }
    if ($LASTEXITCODE -ne 0) { throw 'Docker startup failed. Run: docker compose logs --tail 100' }
    & docker compose ps
    $portOutput = @(& docker compose port web 8080)
    if ($LASTEXITCODE -ne 0 -or $portOutput.Count -eq 0) { throw 'Cannot find the published web port.' }
    $binding = $portOutput[0].Trim()
    if (-not $binding) { throw 'The published web port is empty.' }
    $browserAddress = $binding -replace '^0\.0\.0\.0:', '127.0.0.1:' -replace '^\[::\]:', '[::1]:'
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '  BID AGENT | READY' -ForegroundColor Green
    Write-Host '  web / api / worker / dispatcher / redis: healthy'
    Write-Host "  Workspace : http://$browserAddress/"
    Write-Host "  API docs  : http://$browserAddress/api/docs"
    Write-Host '  Next: Create project -> Upload original -> View parse result'
    Write-Host '  Logs: docker compose logs -f --tail 100 api worker dispatcher'
    Write-Host '============================================================' -ForegroundColor Cyan
} finally {
    Pop-Location
}
