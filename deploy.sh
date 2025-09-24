#!/bin/bash

# Docker deployment script for Redmine MCP Server
# This script builds and deploys the Docker container with proper configuration

set -e  # Exit on error

echo "🐳 Redmine MCP Server Docker Deployment"
echo "========================================"

# Configuration
CONTAINER_NAME="redmine-mcp-server"
IMAGE_NAME="redmine-mcp"
NETWORK_NAME="redmine-mcp-network"

# Function to check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        echo "❌ Docker is not running. Please start Docker first."
        exit 1
    fi
    echo "✅ Docker is running"
}

# Function to check if .env.docker file exists
check_env_file() {
    if [ ! -f .env.docker ]; then
        echo "❌ .env.docker file not found"
        echo "📋 Creating .env.docker from .env.example..."
        if [ -f .env.example ]; then
            cp .env.example .env.docker
            echo "⚠️  Please edit .env.docker with your Redmine configuration before running again"
            exit 1
        else
            echo "❌ .env.example not found. Please create .env.docker manually"
            exit 1
        fi
    fi
    echo "✅ .env.docker file found"
}

# Function to build Docker image
build_image() {
    echo "🔨 Building Docker image..."
    docker build -t $IMAGE_NAME:latest .
    echo "✅ Docker image built successfully"
}

# Function to create Docker network
create_network() {
    if ! docker network ls | grep -q $NETWORK_NAME; then
        echo "🌐 Creating Docker network: $NETWORK_NAME"
        docker network create $NETWORK_NAME
    else
        echo "✅ Docker network $NETWORK_NAME already exists"
    fi
}

# Function to stop and remove existing container
cleanup_container() {
    if docker ps -q -f name=$CONTAINER_NAME | grep -q .; then
        echo "🛑 Stopping existing container..."
        docker stop $CONTAINER_NAME
    fi
    
    if docker ps -aq -f name=$CONTAINER_NAME | grep -q .; then
        echo "🗑️  Removing existing container..."
        docker rm $CONTAINER_NAME
    fi
}

# Function to run the container
run_container() {
    echo "🚀 Starting container..."
    docker run -d \
        --name $CONTAINER_NAME \
        --network $NETWORK_NAME \
        -p 8000:8000 \
        --env-file .env.docker \
        -v "$(pwd)/logs:/app/logs" \
        -v "$(pwd)/data:/app/data" \
        --restart unless-stopped \
        $IMAGE_NAME:latest
    
    echo "✅ Container started successfully"
    echo "📊 Container status:"
    docker ps -f name=$CONTAINER_NAME --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
}

# Function to show logs
show_logs() {
    echo "📋 Container logs (last 20 lines):"
    echo "--------------------------------"
    docker logs --tail 20 $CONTAINER_NAME
    echo "--------------------------------"
    echo "💡 To follow logs: docker logs -f $CONTAINER_NAME"
}

# Function to test the deployment
test_deployment() {
    echo "🧪 Testing deployment..."
    sleep 5  # Wait for container to start
    
    if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Health check passed"
    else
        echo "⚠️  Health check failed - checking if server is starting..."
        sleep 10
        if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
            echo "✅ Health check passed (after delay)"
        else
            echo "❌ Health check failed"
            echo "🔍 Container logs:"
            docker logs --tail 10 $CONTAINER_NAME
        fi
    fi
}

# Function to display usage information
show_usage() {
    cat << EOF
🐳 Redmine MCP Server Docker Deployment Script

Usage: $0 [OPTIONS]

Options:
    --build-only    Build the Docker image only
    --no-test      Skip deployment testing
    --cleanup      Stop and remove container
    --logs         Show container logs
    --status       Show container status
    --help         Show this help message

Examples:
    $0                  # Full deployment (build + run + test)
    $0 --build-only     # Build image only
    $0 --cleanup        # Clean up existing deployment
    $0 --logs           # Show current container logs
    $0 --status         # Show container status

Container will be available at: http://localhost:8000
MCP endpoint: http://localhost:8000/mcp

EOF
}

# Parse command line arguments
BUILD_ONLY=false
NO_TEST=false
CLEANUP_ONLY=false
LOGS_ONLY=false
STATUS_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --build-only)
            BUILD_ONLY=true
            shift
            ;;
        --no-test)
            NO_TEST=true
            shift
            ;;
        --cleanup)
            CLEANUP_ONLY=true
            shift
            ;;
        --logs)
            LOGS_ONLY=true
            shift
            ;;
        --status)
            STATUS_ONLY=true
            shift
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Main execution flow
main() {
    check_docker
    
    if [ "$LOGS_ONLY" = true ]; then
        show_logs
        exit 0
    fi
    
    if [ "$STATUS_ONLY" = true ]; then
        echo "📊 Container status:"
        docker ps -f name=$CONTAINER_NAME --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        exit 0
    fi
    
    if [ "$CLEANUP_ONLY" = true ]; then
        cleanup_container
        echo "✅ Cleanup completed"
        exit 0
    fi
    
    check_env_file
    build_image
    
    if [ "$BUILD_ONLY" = true ]; then
        echo "✅ Build completed. Image: $IMAGE_NAME:latest"
        exit 0
    fi
    
    create_network
    cleanup_container
    run_container
    
    if [ "$NO_TEST" = false ]; then
        test_deployment
    fi
    
    echo ""
    echo "🎉 Deployment completed!"
    echo "🌐 Server URL: http://localhost:8000"
    echo "🔗 MCP Endpoint: http://localhost:8000/mcp"
    echo "📋 View logs: docker logs -f $CONTAINER_NAME"
    echo "🛑 Stop container: docker stop $CONTAINER_NAME"
}

# Run main function
main "$@"
