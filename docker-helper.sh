#!/bin/bash
# ============================================================================
# Telegram Webhook Gateway - Docker Management Helper Scripts
# ============================================================================
# Usage: chmod +x docker-helper.sh && ./docker-helper.sh <command>
# ============================================================================

set -e

PROJECT_NAME="telegram-webhook-gateway"
CONTAINER_NAME="telegram-webhook-gateway"
DATA_DIR="./data"
LOGS_DIR="./logs"
BACKUP_DIR="./backups"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# Helper Functions
# ============================================================================

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    if ! command -v docker compose &> /dev/null; then
        print_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
}

ensure_env_file() {
    if [ ! -f .env ]; then
        print_error ".env file not found!"
        print_status "Creating .env from .env.example..."
        if [ -f .env.example ]; then
            cp .env.example .env
            chmod 600 .env
            print_success ".env created. Please edit it with your settings."
        else
            print_error ".env.example not found either!"
            exit 1
        fi
    fi
}

# ============================================================================
# Commands
# ============================================================================

cmd_help() {
    cat << EOF
${BLUE}Telegram Webhook Gateway - Docker Helper${NC}

${GREEN}Usage:${NC} ./docker-helper.sh <command>

${GREEN}Available Commands:${NC}

  ${YELLOW}Setup & Build:${NC}
    setup           Initialize project (.env, directories)
    build           Build Docker image
    rebuild         Rebuild Docker image (no cache)

  ${YELLOW}Container Management:${NC}
    start           Start container (docker compose up -d)
    stop            Stop container gracefully
    restart         Restart container
    status          Show container status
    ps              Show running containers

  ${YELLOW}Monitoring & Logs:${NC}
    logs            Show live logs (tail -f)
    logs-tail N     Show last N log lines (default: 100)
    stats           Show container resource usage
    health          Check application health

  ${YELLOW}Database & Data:${NC}
    backup          Create SQLite database backup
    restore-backup  List available backups
    clean-db        Delete database (⚠️  WARNING)

  ${YELLOW}Updates & Maintenance:${NC}
    update          Pull latest code and rebuild
    clean           Remove all containers and volumes
    clean-logs      Delete logs directory

  ${YELLOW}Testing & Info:${NC}
    info            Show project information
    test-webhook    Test webhook endpoint with curl
    env-check       Validate .env file syntax

  ${YELLOW}Development:${NC}
    shell           Open bash shell in running container
    exec CMD        Execute command in container

  ${YELLOW}Other:${NC}
    help            Show this help message

${BLUE}Examples:${NC}
  ./docker-helper.sh setup
  ./docker-helper.sh start
  ./docker-helper.sh logs
  ./docker-helper.sh backup
  ./docker-helper.sh exec curl http://localhost:8000/health

EOF
}

cmd_setup() {
    print_status "Setting up project..."
    
    # Create required directories
    mkdir -p "$DATA_DIR" "$LOGS_DIR" "$BACKUP_DIR"
    
    # Ensure .env exists
    ensure_env_file
    
    # Set permissions
    chmod 600 .env 2>/dev/null || true
    chmod 755 "$DATA_DIR" "$LOGS_DIR" "$BACKUP_DIR"
    
    print_success "Setup complete!"
    print_status "Next steps:"
    echo "  1. Edit .env file with your Telegram bot token and webhooks"
    echo "  2. Run: ./docker-helper.sh build"
    echo "  3. Run: ./docker-helper.sh start"
}

cmd_build() {
    check_docker
    ensure_env_file
    print_status "Building Docker image..."
    docker compose build
    print_success "Image built successfully!"
}

cmd_rebuild() {
    check_docker
    ensure_env_file
    print_status "Rebuilding Docker image (no cache)..."
    docker compose build --no-cache
    print_success "Image rebuilt successfully!"
}

cmd_start() {
    check_docker
    ensure_env_file
    
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        print_warning "Container is already running!"
        return
    fi
    
    print_status "Starting container..."
    docker compose up -d
    print_success "Container started!"
    
    # Wait for health check
    print_status "Waiting for container to become healthy..."
    sleep 3
    cmd_health
}

cmd_stop() {
    check_docker
    
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        print_warning "Container is not running!"
        return
    fi
    
    print_status "Stopping container..."
    docker compose down
    print_success "Container stopped!"
}

cmd_restart() {
    check_docker
    print_status "Restarting container..."
    docker compose restart
    print_success "Container restarted!"
    sleep 2
    cmd_health
}

cmd_status() {
    check_docker
    print_status "Container status:"
    docker compose ps
}

cmd_ps() {
    check_docker
    docker ps --filter "name=telegram" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
}

cmd_logs() {
    check_docker
    print_status "Showing live logs (Press Ctrl+C to exit)..."
    docker compose logs -f --tail 100
}

cmd_logs_tail() {
    local lines=${1:-100}
    check_docker
    docker compose logs --tail "$lines"
}

cmd_stats() {
    check_docker
    print_status "Container resource usage:"
    docker stats "${CONTAINER_NAME}" --no-stream
}

cmd_health() {
    print_status "Checking application health..."
    
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        print_error "Container is not running!"
        return 1
    fi
    
    if command -v curl &> /dev/null; then
        local response=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "000")
        
        if [ "$response" = "200" ]; then
            print_success "Application is healthy! (HTTP $response)"
            # Try to show stats
            if curl -s http://localhost:8000/stats 2>/dev/null > /dev/null; then
                echo ""
                print_status "Queue statistics:"
                curl -s http://localhost:8000/stats | python3 -m json.tool 2>/dev/null || echo "  (stats endpoint available)"
            fi
        else
            print_error "Application returned HTTP $response"
            return 1
        fi
    else
        print_warning "curl not available, checking container health..."
        docker compose exec -T telegram-gateway curl -f http://localhost:8000/health || return 1
    fi
}

cmd_backup() {
    mkdir -p "$BACKUP_DIR"
    
    if [ ! -f "$DATA_DIR/events.db" ]; then
        print_error "Database file not found: $DATA_DIR/events.db"
        return 1
    fi
    
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/events.db.${timestamp}.backup"
    
    print_status "Creating backup..."
    cp "$DATA_DIR/events.db" "$backup_file"
    print_success "Backup created: $backup_file"
    ls -lh "$backup_file"
}

cmd_restore_backup() {
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR")" ]; then
        print_error "No backups found in $BACKUP_DIR"
        return 1
    fi
    
    print_status "Available backups:"
    ls -lh "$BACKUP_DIR" | tail -n +2
    
    echo ""
    read -p "Enter backup filename to restore (or press Ctrl+C to cancel): " backup_file
    
    if [ ! -f "$BACKUP_DIR/$backup_file" ]; then
        print_error "Backup file not found!"
        return 1
    fi
    
    read -p "WARNING: This will overwrite current database. Continue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        print_status "Restore cancelled."
        return
    fi
    
    print_status "Restoring backup..."
    cmd_stop
    cp "$BACKUP_DIR/$backup_file" "$DATA_DIR/events.db"
    cmd_start
    print_success "Backup restored!"
}

cmd_clean_db() {
    print_warning "WARNING: This will delete the SQLite database!"
    read -p "Are you sure? Type 'yes' to confirm: " confirm
    
    if [ "$confirm" != "yes" ]; then
        print_status "Operation cancelled."
        return
    fi
    
    cmd_stop
    print_status "Deleting database..."
    rm -f "$DATA_DIR/events.db"
    print_success "Database deleted!"
    cmd_start
}

cmd_update() {
    check_docker
    print_status "Pulling latest code..."
    git pull origin main
    
    print_status "Rebuilding image..."
    cmd_rebuild
    
    print_status "Restarting container..."
    cmd_restart
    
    print_success "Update complete!"
}

cmd_clean() {
    check_docker
    print_warning "WARNING: This will remove containers and volumes!"
    read -p "Are you sure? Type 'yes' to confirm: " confirm
    
    if [ "$confirm" != "yes" ]; then
        print_status "Operation cancelled."
        return
    fi
    
    print_status "Cleaning up..."
    docker compose down -v
    print_success "Cleanup complete!"
}

cmd_clean_logs() {
    if [ -d "$LOGS_DIR" ]; then
        print_status "Deleting logs directory..."
        rm -rf "$LOGS_DIR"
        mkdir -p "$LOGS_DIR"
        print_success "Logs deleted!"
    fi
}

cmd_info() {
    print_status "Project information:"
    echo ""
    echo "  Project Name:    $PROJECT_NAME"
    echo "  Container Name:  $CONTAINER_NAME"
    echo "  Data Dir:        $DATA_DIR"
    echo "  Logs Dir:        $LOGS_DIR"
    echo "  Backups Dir:     $BACKUP_DIR"
    echo ""
    
    check_docker
    
    if [ -d ".git" ]; then
        local branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
        local commit=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
        echo "  Git Branch:      $branch"
        echo "  Git Commit:      $commit"
        echo ""
    fi
    
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "  Status:          🟢 Running"
        local uptime=$(docker inspect "${CONTAINER_NAME}" --format='{{.State.StartedAt}}' 2>/dev/null)
        echo "  Started At:      $uptime"
    else
        echo "  Status:          🔴 Not Running"
    fi
    
    echo ""
    echo "  Database Size:"
    if [ -f "$DATA_DIR/events.db" ]; then
        du -h "$DATA_DIR/events.db"
    else
        echo "    (no database file yet)"
    fi
}

cmd_test_webhook() {
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        print_error "Container is not running!"
        return 1
    fi
    
    print_status "Testing webhook endpoint..."
    
    if command -v curl &> /dev/null; then
        local url="http://localhost:8000/health"
        print_status "GET $url"
        curl -v "$url"
    else
        print_warning "curl not available"
        docker compose exec -T telegram-gateway curl -v http://localhost:8000/health
    fi
}

cmd_env_check() {
    ensure_env_file
    
    print_status "Checking .env file..."
    
    local required_vars=("BOT_TOKEN" "TARGET_WEBHOOK_URL" "TELEGRAM_SECRET_TOKEN")
    local missing=0
    
    for var in "${required_vars[@]}"; do
        if grep -q "^${var}=" .env && ! grep "^${var}=$" .env > /dev/null; then
            echo "  ✓ $var is set"
        else
            echo "  ✗ $var is NOT set or empty"
            missing=$((missing + 1))
        fi
    done
    
    echo ""
    if [ $missing -eq 0 ]; then
        print_success "All required variables are set!"
    else
        print_warning "$missing required variable(s) missing!"
    fi
}

cmd_shell() {
    check_docker
    
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        print_error "Container is not running!"
        return 1
    fi
    
    print_status "Opening bash shell in container..."
    docker compose exec telegram-gateway /bin/bash
}

cmd_exec() {
    check_docker
    
    if [ $# -lt 1 ]; then
        print_error "Please provide a command to execute"
        return 1
    fi
    
    shift  # Remove 'exec' from arguments
    docker compose exec -T telegram-gateway "$@"
}

# ============================================================================
# Main
# ============================================================================

main() {
    local cmd="${1:-help}"
    
    case "$cmd" in
        help)          cmd_help ;;
        setup)         cmd_setup ;;
        build)         cmd_build ;;
        rebuild)       cmd_rebuild ;;
        start)         cmd_start ;;
        stop)          cmd_stop ;;
        restart)       cmd_restart ;;
        status)        cmd_status ;;
        ps)            cmd_ps ;;
        logs)          cmd_logs ;;
        logs-tail)     cmd_logs_tail "$2" ;;
        stats)         cmd_stats ;;
        health)        cmd_health ;;
        backup)        cmd_backup ;;
        restore-backup) cmd_restore_backup ;;
        clean-db)      cmd_clean_db ;;
        update)        cmd_update ;;
        clean)         cmd_clean ;;
        clean-logs)    cmd_clean_logs ;;
        info)          cmd_info ;;
        test-webhook)  cmd_test_webhook ;;
        env-check)     cmd_env_check ;;
        shell)         cmd_shell ;;
        exec)          cmd_exec "$@" ;;
        *)
            print_error "Unknown command: $cmd"
            cmd_help
            exit 1
            ;;
    esac
}

main "$@"
