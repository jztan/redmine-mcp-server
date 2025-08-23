#!/bin/bash
set -e

# AgentCore AWS Deployment Cleanup Script
# This script cleans up AWS resources created during AgentCore deployment

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DRY_RUN=false
FORCE=false
DOCKER_ONLY=false
INTERACTIVE=true

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            echo -e "${YELLOW}🔍 DRY RUN MODE: No actual changes will be made${NC}"
            shift
            ;;
        --force)
            FORCE=true
            INTERACTIVE=false
            echo -e "${RED}⚠️  FORCE MODE: No confirmation prompts${NC}"
            shift
            ;;
        --docker-only)
            DOCKER_ONLY=true
            echo -e "${BLUE}🐳 DOCKER ONLY: Will clean up only Docker resources${NC}"
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dry-run      Preview what would be deleted without making changes"
            echo "  --force        Skip confirmation prompts (dangerous!)"
            echo "  --docker-only  Clean up only Docker resources (local + ECR)"
            echo "  --help, -h     Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Interactive cleanup with confirmation"
            echo "  $0 --dry-run          # Preview cleanup actions"
            echo "  $0 --docker-only      # Clean only Docker resources"
            echo "  $0 --force            # Clean everything without prompts"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}🧹 AgentCore AWS Deployment Cleanup${NC}"
echo "=================================================="

# Load environment variables
ENV_FILE=".env.agentcore"
if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
    echo -e "${GREEN}✅ Loaded configuration from $ENV_FILE${NC}"
else
    echo -e "${RED}❌ Configuration file $ENV_FILE not found${NC}"
    echo "Please ensure you're running this from the deployment/agentcore directory"
    echo "and that you have a .env.agentcore file configured"
    exit 1
fi

# Validate required AWS variables
if [ -z "$AWS_REGION" ] || [ -z "$ECR_REPOSITORY" ]; then
    echo -e "${RED}❌ Missing required environment variables${NC}"
    echo "Required: AWS_REGION, ECR_REPOSITORY"
    exit 1
fi

# Extract repository name from ECR URI
ECR_REPOSITORY_NAME=$(echo "$ECR_REPOSITORY" | sed 's|.*/||')

echo "Configuration:"
echo "  AWS Region: $AWS_REGION"
echo "  ECR Repository: $ECR_REPOSITORY_NAME"
echo ""

# Function to execute or preview commands
execute_command() {
    local cmd="$1"
    local description="$2"
    
    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY RUN] $description${NC}"
        echo "  Command: $cmd"
    else
        echo -e "${BLUE}$description${NC}"
        if eval "$cmd"; then
            echo -e "${GREEN}✅ Success${NC}"
        else
            echo -e "${YELLOW}⚠️  Command failed (resource might not exist)${NC}"
        fi
    fi
    echo ""
}

# Function to confirm action
confirm_action() {
    local message="$1"
    
    if [ "$INTERACTIVE" = false ]; then
        return 0
    fi
    
    echo -e "${YELLOW}$message${NC}"
    read -p "Continue? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled by user"
        exit 0
    fi
}

# Check AWS CLI and credentials
echo -e "${BLUE}🔍 Checking AWS configuration...${NC}"
if ! command -v aws &> /dev/null; then
    echo -e "${RED}❌ AWS CLI not found. Please install AWS CLI first.${NC}"
    exit 1
fi

if ! aws sts get-caller-identity --region "$AWS_REGION" &> /dev/null; then
    echo -e "${RED}❌ AWS credentials not configured or invalid${NC}"
    echo "Please configure AWS credentials using 'aws configure' or environment variables"
    exit 1
fi

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "$AWS_REGION")
echo -e "${GREEN}✅ AWS authenticated as account: $AWS_ACCOUNT_ID${NC}"
echo ""

# Check if ECR repository exists
ECR_EXISTS=false
if aws ecr describe-repositories --repository-names "$ECR_REPOSITORY_NAME" --region "$AWS_REGION" &> /dev/null; then
    ECR_EXISTS=true
    echo -e "${GREEN}✅ ECR repository '$ECR_REPOSITORY_NAME' found${NC}"
else
    echo -e "${YELLOW}⚠️  ECR repository '$ECR_REPOSITORY_NAME' not found${NC}"
fi

# Clean up ECR images
if [ "$ECR_EXISTS" = true ]; then
    echo -e "${BLUE}🗑️  ECR Image Cleanup${NC}"
    echo "=================================="
    
    # List images in repository
    IMAGES=$(aws ecr list-images --repository-name "$ECR_REPOSITORY_NAME" --region "$AWS_REGION" --query 'imageIds[*]' --output text 2>/dev/null || echo "")
    
    if [ -n "$IMAGES" ]; then
        echo "Found images in ECR repository:"
        aws ecr list-images --repository-name "$ECR_REPOSITORY_NAME" --region "$AWS_REGION" --query 'imageIds[*].[imageTag,imageDigest]' --output table || true
        echo ""
        
        confirm_action "🗑️  Delete all images from ECR repository '$ECR_REPOSITORY_NAME'?"
        
        # Delete all images
        execute_command "aws ecr batch-delete-image --repository-name '$ECR_REPOSITORY_NAME' --region '$AWS_REGION' --image-ids \"\$(aws ecr list-images --repository-name '$ECR_REPOSITORY_NAME' --region '$AWS_REGION' --query 'imageIds[*]' --output json)\"" "Deleting all images from ECR repository"
    else
        echo -e "${GREEN}✅ No images found in ECR repository${NC}"
        echo ""
    fi
    
    # Option to delete ECR repository
    if [ "$DOCKER_ONLY" = false ]; then
        confirm_action "🗑️  Delete the entire ECR repository '$ECR_REPOSITORY_NAME'?"
        execute_command "aws ecr delete-repository --repository-name '$ECR_REPOSITORY_NAME' --region '$AWS_REGION' --force" "Deleting ECR repository"
    fi
fi

# Clean up local Docker images
echo -e "${BLUE}🐳 Local Docker Cleanup${NC}"
echo "=================================="

# Check for local images
LOCAL_IMAGES=$(docker images --filter=reference="redmine-mcp-agentcore*" -q 2>/dev/null || echo "")
if [ -n "$LOCAL_IMAGES" ]; then
    echo "Found local AgentCore images:"
    docker images --filter=reference="redmine-mcp-agentcore*" --format "table {{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}" || true
    echo ""
    
    confirm_action "🗑️  Delete local AgentCore Docker images?"
    execute_command "docker rmi -f \$(docker images --filter=reference='redmine-mcp-agentcore*' -q)" "Removing local AgentCore images"
else
    echo -e "${GREEN}✅ No local AgentCore images found${NC}"
    echo ""
fi

# Check for ECR-tagged images
ECR_IMAGES=$(docker images --filter=reference="*$ECR_REPOSITORY_NAME*" -q 2>/dev/null || echo "")
if [ -n "$ECR_IMAGES" ]; then
    echo "Found ECR-tagged images:"
    docker images --filter=reference="*$ECR_REPOSITORY_NAME*" --format "table {{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}" || true
    echo ""
    
    confirm_action "🗑️  Delete ECR-tagged Docker images?"
    execute_command "docker rmi -f \$(docker images --filter=reference='*$ECR_REPOSITORY_NAME*' -q)" "Removing ECR-tagged images"
fi

# Clean up build cache
confirm_action "🗑️  Clean Docker build cache and dangling images?"
execute_command "docker system prune -f" "Cleaning Docker build cache"

if [ "$DOCKER_ONLY" = false ]; then
    echo -e "${BLUE}☁️  AWS Service Cleanup${NC}"
    echo "=================================="
    
    # Optional: Clean up ECS services
    echo "Note: This script focuses on ECR cleanup."
    echo "If you have deployed ECS services or Lambda functions, clean them up manually:"
    echo ""
    echo "For ECS:"
    echo "  aws ecs update-service --cluster YOUR_CLUSTER --service YOUR_SERVICE --desired-count 0"
    echo "  aws ecs delete-service --cluster YOUR_CLUSTER --service YOUR_SERVICE"
    echo ""
    echo "For Lambda:"
    echo "  aws lambda delete-function --function-name YOUR_FUNCTION_NAME"
    echo ""
    echo "For CloudWatch Logs:"
    echo "  aws logs delete-log-group --log-group-name /aws/lambda/YOUR_FUNCTION_NAME"
    echo "  aws logs delete-log-group --log-group-name /ecs/redmine-mcp-agentcore"
    echo ""
    
    # Check for common CloudWatch log groups
    echo "Checking for related CloudWatch log groups..."
    LOG_GROUPS=$(aws logs describe-log-groups --region "$AWS_REGION" --log-group-name-prefix "/aws/lambda/redmine" --query 'logGroups[*].logGroupName' --output text 2>/dev/null || echo "")
    if [ -n "$LOG_GROUPS" ]; then
        echo "Found related log groups: $LOG_GROUPS"
        confirm_action "🗑️  Delete these CloudWatch log groups?"
        for LOG_GROUP in $LOG_GROUPS; do
            execute_command "aws logs delete-log-group --log-group-name '$LOG_GROUP' --region '$AWS_REGION'" "Deleting log group: $LOG_GROUP"
        done
    fi
    
    # Check ECS log groups
    ECS_LOG_GROUPS=$(aws logs describe-log-groups --region "$AWS_REGION" --log-group-name-prefix "/ecs/redmine-mcp" --query 'logGroups[*].logGroupName' --output text 2>/dev/null || echo "")
    if [ -n "$ECS_LOG_GROUPS" ]; then
        echo "Found ECS log groups: $ECS_LOG_GROUPS"
        confirm_action "🗑️  Delete these ECS CloudWatch log groups?"
        for LOG_GROUP in $ECS_LOG_GROUPS; do
            execute_command "aws logs delete-log-group --log-group-name '$LOG_GROUP' --region '$AWS_REGION'" "Deleting ECS log group: $LOG_GROUP"
        done
    fi
fi

echo ""
echo -e "${GREEN}🎉 Cleanup completed!${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}📝 This was a dry run - no actual changes were made${NC}"
    echo "Run the script without --dry-run to perform the actual cleanup"
fi

echo ""
echo "Summary of what was cleaned:"
if [ "$ECR_EXISTS" = true ]; then
    echo "  ✅ ECR repository images"
    if [ "$DOCKER_ONLY" = false ]; then
        echo "  ✅ ECR repository (if confirmed)"
    fi
fi
echo "  ✅ Local Docker images"
echo "  ✅ Docker build cache"
if [ "$DOCKER_ONLY" = false ]; then
    echo "  ✅ CloudWatch log groups (if found and confirmed)"
fi

echo ""
echo -e "${BLUE}💡 Tips:${NC}"
echo "  • Review any remaining AWS resources manually"
echo "  • Check your AWS billing dashboard"
echo "  • Consider deleting the .env.agentcore file if no longer needed"
echo "  • Keep this cleanup script for future deployments"