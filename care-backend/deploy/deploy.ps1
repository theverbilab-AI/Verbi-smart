# Build care-backend Docker image, push to ECR, and force ECS redeploy.
# Prerequisites: AWS CLI configured (aws configure), Docker running.
#
# Usage:
#   cd care-backend
#   .\deploy\deploy.ps1
# Optional env:
#   $env:AWS_REGION = "us-east-1"
#   $env:ECR_REPOSITORY = "verbilab-care-backend"
#   $env:ECS_CLUSTER = "default"
#   $env:ECS_SERVICE = "care-backend"

param(
    [string]$Region = $env:AWS_REGION ?? "us-east-1",
    [string]$Repository = $env:ECR_REPOSITORY ?? "verbilab-care-backend",
    [string]$Cluster = $env:ECS_CLUSTER ?? "default",
    [string]$Service = $env:ECS_SERVICE ?? "care-backend"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location (Join-Path $Root "care-backend")

Write-Host "==> AWS account"
$account = (aws sts get-caller-identity --query Account --output text).Trim()
Write-Host "Account: $account  Region: $Region"

Write-Host "==> Ensure ECR repo $Repository"
aws ecr describe-repositories --repository-names $Repository --region $Region 2>$null
if ($LASTEXITCODE -ne 0) {
    aws ecr create-repository --repository-name $Repository --region $Region | Out-Null
}

$registry = "$account.dkr.ecr.$Region.amazonaws.com"
$image = "$registry/${Repository}:latest"

Write-Host "==> ECR login"
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $registry

Write-Host "==> Docker build"
docker build -t $image .

Write-Host "==> Push"
docker push $image

Write-Host "==> ECS force new deployment ($Cluster / $Service)"
aws ecs update-service `
    --cluster $Cluster `
    --service $Service `
    --force-new-deployment `
    --region $Region `
    --output table

Write-Host "Done. Wait 2-3 min, then check https://verbilab.com/api/health (or your API URL)."
