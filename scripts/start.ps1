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
    if ($NoBuild) { & docker compose up -d --wait --wait-timeout 120 }
    else { & docker compose up -d --build --wait --wait-timeout 120 }
    if ($LASTEXITCODE -ne 0) { throw 'Docker startup failed. Run: docker compose logs --tail 100' }
    & docker compose ps
    Write-Host 'Open the published web port above (default: http://127.0.0.1:8080).'
} finally {
    Pop-Location
}
