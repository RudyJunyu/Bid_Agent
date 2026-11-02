#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
    cp .env.example .env
    echo 'Created .env. Configure LLM / MinerU credentials for those features.'
fi
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 180
docker compose ps
binding=$(docker compose port web 8080 | head -n 1)
test -n "$binding"
browser_address=$(printf '%s' "$binding" | sed 's/^0\.0\.0\.0:/127.0.0.1:/;s/^\[::\]:/[::1]:/')
printf '\n============================================================\n'
echo '  BID AGENT | READY'
echo '  web / api / worker / dispatcher / redis: healthy'
echo "  Workspace : http://$browser_address/"
echo "  API docs  : http://$browser_address/api/docs"
echo '  Next: Create project -> Upload original -> View parse result'
echo '  Logs: docker compose logs -f --tail 100 api worker dispatcher'
echo '============================================================'
