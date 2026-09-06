<#
deploy.ps1 - DisputeDesk to ECS Fargate in one run, with NO local Docker.
  The image is built by AWS CodeBuild from a source zip in S3, pushed to ECR, then run behind an ALB.
  Idempotent: every step checks for the resource before creating it, so re-running is safe.

  .\infra\deploy.ps1                                  # mock mode (no Bedrock needed)
  .\infra\deploy.ps1 -Provider bedrock                # live model via the task role
  .\infra\deploy.ps1 -Profile disputedesk -Region us-east-1 -Name disputedesk

Prereqs: AWS CLI v2, a profile with deploy rights, Bedrock model access enabled if -Provider bedrock.
#>
param(
  [string]$Profile = "disputedesk",
  [string]$Region = "us-east-1",
  [string]$Name = "disputedesk",
  [ValidateSet("mock", "bedrock")][string]$Provider = "mock",
  [string]$ModelId = "us.anthropic.claude-sonnet-4-6",
  [switch]$SkipBuild
)
$ErrorActionPreference = "Continue"
$aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
if (-not (Test-Path $aws)) { $aws = "aws" }
$root = Split-Path $PSScriptRoot -Parent
$tag = Get-Date -Format "yyyyMMdd-HHmmss"

function A {                          # run aws, return trimmed stdout, throw on failure
  $out = & $aws --profile $Profile --region $Region @args 2>$null
  if ($LASTEXITCODE -ne 0) { throw "aws $($args -join ' ') failed (exit $LASTEXITCODE)" }
  if ($null -eq $out) { return "" }
  return ($out -join "`n").Trim()
}
function Try-A {                      # run aws, return $null instead of throwing
  $out = & $aws --profile $Profile --region $Region @args 2>$null
  if ($LASTEXITCODE -ne 0) { return $null }
  if ($null -eq $out) { return "" }
  return ($out -join "`n").Trim()
}
function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

# ---------------------------------------------------------------- 0. identity
Step "identity"
$acct = A sts get-caller-identity --query Account --output text
Write-Host "account $acct  region $Region  profile $Profile  provider $Provider"

# ---------------------------------------------------------------- 1. ECR
Step "ECR repository"
$ecrUri = Try-A ecr describe-repositories --repository-names $Name --query "repositories[0].repositoryUri" --output text
if (-not $ecrUri) { $ecrUri = A ecr create-repository --repository-name $Name --image-scanning-configuration scanOnPush=true --query "repository.repositoryUri" --output text }
Write-Host $ecrUri

$tmp = Join-Path $env:TEMP "$Name-cb"
New-Item -ItemType Directory -Force $tmp | Out-Null

# ---------------------------------------------------------------- 2. source zip -> S3
if ($SkipBuild) {
  Step "reusing newest image in ECR (-SkipBuild)"
  $latest = A ecr describe-images --repository-name $Name --query "sort_by(imageDetails,&imagePushedAt)[-1].imageTags[0]" --output text
  $image = "${ecrUri}:$latest"
  Write-Host $image
} else {
  Step "source zip -> S3"
  $bucket = "$Name-src-$acct"
  if ($null -eq (Try-A s3api head-bucket --bucket $bucket)) {
    if ($Region -eq "us-east-1") { A s3api create-bucket --bucket $bucket | Out-Null }
    else { A s3api create-bucket --bucket $bucket --create-bucket-configuration LocationConstraint=$Region | Out-Null }
  }
  $stage = Join-Path $env:TEMP "$Name-src"
  if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
  robocopy $root $stage /E /XD .venv .git __pycache__ .pytest_cache audit .index /XF .env *.jsonl *.faiss /NFL /NDL /NJH /NJS | Out-Null
  $zip = Join-Path $env:TEMP "$Name-src.zip"
  if (Test-Path $zip) { Remove-Item $zip -Force }
  Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
  A s3 cp $zip "s3://$bucket/source.zip" | Out-Null
  Write-Host "s3://$bucket/source.zip ($([math]::Round((Get-Item $zip).Length/1KB)) KB)"

  # ---------------------------------------------------------------- 3. CodeBuild role + project
  Step "CodeBuild role"
  $cbRole = "$Name-codebuild-role"
  $cbTrust = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"codebuild.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
  $cbPolicy = @"
  {"Version":"2012-10-17","Statement":[
   {"Effect":"Allow","Action":["ecr:GetAuthorizationToken"],"Resource":"*"},
   {"Effect":"Allow","Action":["ecr:BatchCheckLayerAvailability","ecr:CompleteLayerUpload","ecr:InitiateLayerUpload","ecr:PutImage","ecr:UploadLayerPart","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],"Resource":"arn:aws:ecr:${Region}:${acct}:repository/${Name}"},
   {"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion"],"Resource":"arn:aws:s3:::${bucket}/*"},
   {"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],"Resource":"*"}]}
"@
  Set-Content -Path "$tmp\trust.json" -Value $cbTrust -Encoding ascii
  Set-Content -Path "$tmp\policy.json" -Value $cbPolicy -Encoding ascii
  $cbRoleArn = Try-A iam get-role --role-name $cbRole --query Role.Arn --output text
  if (-not $cbRoleArn) {
    $cbRoleArn = A iam create-role --role-name $cbRole --assume-role-policy-document "file://$tmp/trust.json" --query Role.Arn --output text
    Start-Sleep 10                                        # IAM propagation
  }
  A iam put-role-policy --role-name $cbRole --policy-name build-push --policy-document "file://$tmp/policy.json" | Out-Null

  Step "CodeBuild project"
  $envVars = "[{name=ECR_URI,value=$ecrUri},{name=IMAGE_TAG,value=$tag}]"
  $envArg = "type=LINUX_CONTAINER,image=aws/codebuild/standard:7.0,computeType=BUILD_GENERAL1_SMALL,privilegedMode=true,environmentVariables=$envVars"
  $srcArg = "type=S3,location=$bucket/source.zip"
  $exists = Try-A codebuild batch-get-projects --names $Name --query "projects[0].name" --output text
  if ($exists -and $exists -ne "None") {
    A codebuild update-project --name $Name --source $srcArg --environment $envArg --service-role $cbRoleArn | Out-Null
  } else {
    A codebuild create-project --name $Name --source $srcArg --artifacts type=NO_ARTIFACTS --environment $envArg --service-role $cbRoleArn | Out-Null
  }

  Step "build image in the cloud (3-6 min)"
  $buildId = A codebuild start-build --project-name $Name --query "build.id" --output text
  do {
    Start-Sleep 20
    $status = A codebuild batch-get-builds --ids $buildId --query "builds[0].buildStatus" --output text
    Write-Host "  $status"
  } while ($status -eq "IN_PROGRESS")
  if ($status -ne "SUCCEEDED") { throw "build $buildId ended $status - see CodeBuild console logs" }
  $image = "${ecrUri}:$tag"
  Write-Host $image
}

# ---------------------------------------------------------------- 4. ECS roles
Step "ECS roles"
$execRole = "$Name-execution-role"; $taskRole = "$Name-task-role"
$execArn = Try-A iam get-role --role-name $execRole --query Role.Arn --output text
if (-not $execArn) {
  $execArn = A iam create-role --role-name $execRole --assume-role-policy-document "file://$root/infra/ecs-trust.json" --query Role.Arn --output text
  A iam attach-role-policy --role-name $execRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy | Out-Null
  Start-Sleep 10
}
$taskArn = Try-A iam get-role --role-name $taskRole --query Role.Arn --output text
if (-not $taskArn) {
  $taskArn = A iam create-role --role-name $taskRole --assume-role-policy-document "file://$root/infra/ecs-trust.json" --query Role.Arn --output text
  Start-Sleep 10
}
(Get-Content "$root/infra/task-role-policy.json" -Raw).Replace("ACCOUNT_ID", $acct) | Set-Content "$tmp/task-policy.json" -Encoding ascii
A iam put-role-policy --role-name $taskRole --policy-name bedrock-invoke-one-model --policy-document "file://$tmp/task-policy.json" | Out-Null

# ---------------------------------------------------------------- 5. cluster + task definition
Step "cluster + task definition"
Try-A logs create-log-group --log-group-name "/ecs/$Name" | Out-Null
$clusterStatus = Try-A ecs describe-clusters --clusters $Name --query "clusters[0].status" --output text
if ($clusterStatus -ne "ACTIVE") { A ecs create-cluster --cluster-name $Name | Out-Null }
$td = Get-Content "$root/infra/ecs-task-definition.json" -Raw
$td = $td.Replace("ACCOUNT_ID", $acct).Replace("us-east-1", $Region)
$td = $td -replace '"image": "[^"]+"', ('"image": "' + $image + '"')
$td = $td -replace '\{ "name": "DISPUTEDESK_LLM_PROVIDER", "value": "[^"]+" \}', ('{ "name": "DISPUTEDESK_LLM_PROVIDER", "value": "' + $Provider + '" }')
$td = $td -replace '\{ "name": "BEDROCK_MODEL_ID", "value": "[^"]+" \}', ('{ "name": "BEDROCK_MODEL_ID", "value": "' + $ModelId + '" }')
Set-Content "$tmp/taskdef.json" -Value $td -Encoding ascii
$tdArn = A ecs register-task-definition --cli-input-json "file://$tmp/taskdef.json" --query "taskDefinition.taskDefinitionArn" --output text
Write-Host $tdArn

# ---------------------------------------------------------------- 6. networking
Step "networking (default VPC)"
$vpc = A ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text
$subnets = (A ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc" "Name=default-for-az,Values=true" --query "Subnets[].SubnetId" --output text) -split "\s+"
function Ensure-SG($sgName, $desc) {
  $id = Try-A ec2 describe-security-groups --filters "Name=group-name,Values=$sgName" "Name=vpc-id,Values=$vpc" --query "SecurityGroups[0].GroupId" --output text
  if (-not $id -or $id -eq "None") { $id = A ec2 create-security-group --group-name $sgName --description $desc --vpc-id $vpc --query GroupId --output text }
  return $id
}
$albSg = Ensure-SG "$Name-alb-sg" "DisputeDesk ALB: 80 from anywhere"
$taskSg = Ensure-SG "$Name-task-sg" "DisputeDesk tasks: 8501 from ALB only"
Try-A ec2 authorize-security-group-ingress --group-id $albSg --protocol tcp --port 80 --cidr 0.0.0.0/0 | Out-Null
Try-A ec2 authorize-security-group-ingress --group-id $taskSg --protocol tcp --port 8501 --source-group $albSg | Out-Null

Step "load balancer + target group"
$albArn = Try-A elbv2 describe-load-balancers --names "$Name-alb" --query "LoadBalancers[0].LoadBalancerArn" --output text
if (-not $albArn -or $albArn -eq "None") {
  $albArn = A elbv2 create-load-balancer --name "$Name-alb" --type application --scheme internet-facing --subnets $subnets --security-groups $albSg --query "LoadBalancers[0].LoadBalancerArn" --output text
}
# the service launches tasks in every default subnet, so the ALB must cover every AZ too
A elbv2 set-subnets --load-balancer-arn $albArn --subnets $subnets | Out-Null
A elbv2 modify-load-balancer-attributes --load-balancer-arn $albArn --attributes "Key=idle_timeout.timeout_seconds,Value=300" | Out-Null
$tgArn = Try-A elbv2 describe-target-groups --names "$Name-tg" --query "TargetGroups[0].TargetGroupArn" --output text
if (-not $tgArn -or $tgArn -eq "None") {
  $tgArn = A elbv2 create-target-group --name "$Name-tg" --protocol HTTP --port 8501 --vpc-id $vpc --target-type ip --health-check-path /_stcore/health --health-check-interval-seconds 30 --query "TargetGroups[0].TargetGroupArn" --output text
}
$listener = Try-A elbv2 describe-listeners --load-balancer-arn $albArn --query "Listeners[0].ListenerArn" --output text
if (-not $listener -or $listener -eq "None") {
  A elbv2 create-listener --load-balancer-arn $albArn --protocol HTTP --port 80 --default-actions "Type=forward,TargetGroupArn=$tgArn" | Out-Null
}

# ---------------------------------------------------------------- 7. service
Step "ECS service"
$netCfg = "awsvpcConfiguration={subnets=[$($subnets -join ',')],securityGroups=[$taskSg],assignPublicIp=ENABLED}"
$svcStatus = Try-A ecs describe-services --cluster $Name --services $Name --query "services[0].status" --output text
if ($svcStatus -eq "ACTIVE") {
  A ecs update-service --cluster $Name --service $Name --task-definition $tdArn --force-new-deployment | Out-Null
} else {
  A ecs create-service --cluster $Name --service-name $Name --task-definition $tdArn --desired-count 1 --launch-type FARGATE --network-configuration $netCfg --load-balancers "targetGroupArn=$tgArn,containerName=$Name,containerPort=8501" --health-check-grace-period-seconds 60 | Out-Null
}

$dns = A elbv2 describe-load-balancers --load-balancer-arns $albArn --query "LoadBalancers[0].DNSName" --output text
Step "done"
Write-Host "URL:       http://$dns   (tasks take ~2 min to pass health checks)"
Write-Host "watch:     & '$aws' --profile $Profile --region $Region ecs describe-services --cluster $Name --services $Name --query 'services[0].deployments'"
Write-Host "logs:      & '$aws' --profile $Profile --region $Region logs tail /ecs/$Name --follow"
Write-Host "tear down: .\infra\teardown.ps1"
