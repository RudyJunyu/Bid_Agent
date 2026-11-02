#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
    cp .env.example .env
    echo 'Created .env. Configure LLM / MinerU credentials for those features.'
fi
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 120
docker compose ps
echo 'Open the published web port above (default: http://127.0.0.1:8080).'
