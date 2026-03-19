#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Starting Scientific Navigator demo stack..."
docker compose up -d --build

echo "Waiting for backend..."
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:8000/api/sessions/" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo
echo "Scientific Navigator is starting."
echo "Frontend: http://localhost:3000"
echo "Backend:  http://localhost:8000"
echo
echo "Useful commands:"
echo "  docker compose ps"
echo "  docker compose logs -f backend"
echo "  docker compose logs -f backend-worker"
echo "  ./stop-demo.sh"
