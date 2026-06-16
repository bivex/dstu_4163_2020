#!/usr/bin/env bash

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Workspace directories
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORTAL_DIR="${BASE_DIR}/portal"
FRONTEND_DIR="${BASE_DIR}/external/dms-dir"

function print_help() {
  echo -e "${BLUE}Діловод / DSTU 4163 Management Script${NC}"
  echo -e "Usage: ./manage.sh [command]"
  echo
  echo "Docker Commands:"
  echo -e "  ${GREEN}up${NC}               Build and start backend api in Docker"
  echo -e "  ${GREEN}down${NC}             Stop backend api in Docker"
  echo -e "  ${GREEN}logs${NC}             Follow Docker logs"
  echo -e "  ${GREEN}restart${NC}          Restart Docker containers"
  echo
  echo "Local Backend Commands:"
  echo -e "  ${GREEN}backend-dev${NC}      Run FastAPI backend locally with reload"
  echo -e "  ${GREEN}backend-test${NC}     Run pytest backend unit tests"
  echo
  echo "Local Frontend Commands:"
  echo -e "  ${GREEN}frontend-dev${NC}     Start Nuxt development server"
  echo -e "  ${GREEN}frontend-build${NC}   Build Nuxt application for production"
  echo -e "  ${GREEN}frontend-check${NC}   Run TypeScript typecheck"
  echo
  echo "General Commands:"
  echo -e "  ${GREEN}status${NC}           Show status of containers and ports"
  echo -e "  ${GREEN}help${NC}             Show this help menu"
}

case "$1" in
  up)
    echo -e "${BLUE}Starting Docker containers...${NC}"
    docker compose -f "${BASE_DIR}/docker-compose.yml" up --build -d
    ;;
  down)
    echo -e "${YELLOW}Stopping Docker containers...${NC}"
    docker compose -f "${BASE_DIR}/docker-compose.yml" down
    ;;
  logs)
    docker compose -f "${BASE_DIR}/docker-compose.yml" logs -f
    ;;
  restart)
    echo -e "${BLUE}Restarting Docker containers...${NC}"
    docker compose -f "${BASE_DIR}/docker-compose.yml" restart
    ;;
  backend-dev)
    echo -e "${BLUE}Starting local backend development server...${NC}"
    source "${PORTAL_DIR}/.venv/bin/activate" 2>/dev/null || true
    export PYTHONPATH="${BASE_DIR}/src"
    export PORTAL_DATABASE_URL="sqlite:///${PORTAL_DIR}/portal.db"
    export PORTAL_CORS="*"
    uvicorn portal.main:app --host 0.0.0.0 --port 8000 --app-dir "${BASE_DIR}" --reload
    ;;
  backend-test)
    echo -e "${BLUE}Running backend unit tests...${NC}"
    "${PORTAL_DIR}/.venv/bin/python" -m pytest "${PORTAL_DIR}/tests/"
    ;;
  frontend-dev)
    echo -e "${BLUE}Starting frontend development server...${NC}"
    (cd "${FRONTEND_DIR}" && bun run dev)
    ;;
  frontend-build)
    echo -e "${BLUE}Building frontend application...${NC}"
    (cd "${FRONTEND_DIR}" && bun run build)
    ;;
  frontend-check)
    echo -e "${BLUE}Running frontend typecheck...${NC}"
    (cd "${FRONTEND_DIR}" && bun run typecheck)
    ;;
  status)
    echo -e "${BLUE}=== Docker Containers ===${NC}"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "dstu_4163_2020|NAMES" || echo "No containers running"
    echo
    echo -e "${BLUE}=== Active Ports ===${NC}"
    lsof -i :8000 -i :3000 | grep LISTEN || echo "Ports 8000 (backend) and 3000 (frontend) are free"
    ;;
  *)
    print_help
    ;;
esac
