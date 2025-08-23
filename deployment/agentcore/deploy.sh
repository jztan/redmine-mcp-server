#!/bin/bash
set -e

echo "🚀 Deploying Redmine MCP Server - AgentCore Mode"

# Load environment variables
if [ -f .env.agentcore ]; then
    source .env.agentcore
    echo "✅ Loaded AgentCore configuration"
else
    echo "❌ .env.agentcore not found. Copy from .env.agentcore.example"
    exit 1
fi

# Validate required variables
: ${AWS_REGION:?❌ AWS_REGION not set}
: ${ECR_REPOSITORY:?❌ ECR_REPOSITORY not set}

echo "🏗️  Building Docker image..."
docker build -f deployment/agentcore/Dockerfile.agentcore -t redmine-mcp-agentcore:latest .

echo "🏷️  Tagging image for ECR..."
docker tag redmine-mcp-agentcore:latest $ECR_REPOSITORY:latest

echo "🔐 Logging into ECR..."
aws ecr get-login-password --region $AWS_REGION | \
    docker login --username AWS --password-stdin $ECR_REPOSITORY

echo "📤 Pushing to ECR..."
docker push $ECR_REPOSITORY:latest

echo "✅ AgentCore deployment complete!"
echo "📋 Next steps:"
echo "   1. Configure ECS service or Lambda function"
echo "   2. Set environment variables (REDMINE_URL, REDMINE_API_KEY)"
echo "   3. Test endpoint: POST /mcp"