<# teardown.ps1 - remove everything deploy.ps1 created (stops the bill). Safe to re-run. #>
param([string]$Profile = "disputedesk", [string]$Region = "us-east-1", [string]$Name = "disputedesk")
$ErrorActionPreference = "Continue"
$aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"; if (-not (Test-Path $aws)) { $aws = "aws" }
function Try-A { $out = & $aws --profile $Profile --region $Region @args 2>$null; if ($LASTEXITCODE -ne 0) { return $null }; if ($null -eq $out) { return "" }; return ($out -join "`n").Trim() }
function Step($m) { Write-Host "`n== $m" -ForegroundColor Yellow }
$acct = Try-A sts get-caller-identity --query Account --output text

Step "ECS service + cluster"
Try-A ecs update-service --cluster $Name --service $Name --desired-count 0 | Out-Null
Try-A ecs delete-service --cluster $Name --service $Name --force | Out-Null
Start-Sleep 15
$tds = Try-A ecs list-task-definitions --family-prefix $Name --query "taskDefinitionArns[]" --output text
if ($tds) { foreach ($t in ($tds -split "\s+")) { Try-A ecs deregister-task-definition --task-definition $t | Out-Null } }
Try-A ecs delete-cluster --cluster $Name | Out-Null

Step "ALB, listener, target group"
$albArn = Try-A elbv2 describe-load-balancers --names "$Name-alb" --query "LoadBalancers[0].LoadBalancerArn" --output text
if ($albArn -and $albArn -ne "None") {
  $ls = Try-A elbv2 describe-listeners --load-balancer-arn $albArn --query "Listeners[].ListenerArn" --output text
  if ($ls) { foreach ($l in ($ls -split "\s+")) { Try-A elbv2 delete-listener --listener-arn $l | Out-Null } }
  Try-A elbv2 delete-load-balancer --load-balancer-arn $albArn | Out-Null
  Start-Sleep 30
}
$tg = Try-A elbv2 describe-target-groups --names "$Name-tg" --query "TargetGroups[0].TargetGroupArn" --output text
if ($tg -and $tg -ne "None") { Try-A elbv2 delete-target-group --target-group-arn $tg | Out-Null }

Step "security groups"
$vpc = Try-A ec2 describe-vpcs --filters Name=isDefault,Values=true --query "Vpcs[0].VpcId" --output text
foreach ($sg in @("$Name-task-sg", "$Name-alb-sg")) {
  $id = Try-A ec2 describe-security-groups --filters "Name=group-name,Values=$sg" "Name=vpc-id,Values=$vpc" --query "SecurityGroups[0].GroupId" --output text
  if ($id -and $id -ne "None") { Start-Sleep 5; Try-A ec2 delete-security-group --group-id $id | Out-Null }
}

Step "CodeBuild, ECR, S3, logs"
Try-A codebuild delete-project --name $Name | Out-Null
Try-A ecr delete-repository --repository-name $Name --force | Out-Null
Try-A s3 rb "s3://$Name-src-$acct" --force | Out-Null
Try-A logs delete-log-group --log-group-name "/ecs/$Name" | Out-Null
Try-A logs delete-log-group --log-group-name "/aws/codebuild/$Name" | Out-Null

Step "IAM roles"
Try-A iam delete-role-policy --role-name "$Name-codebuild-role" --policy-name build-push | Out-Null
Try-A iam delete-role --role-name "$Name-codebuild-role" | Out-Null
Try-A iam delete-role-policy --role-name "$Name-task-role" --policy-name bedrock-invoke-one-model | Out-Null
Try-A iam delete-role --role-name "$Name-task-role" | Out-Null
Try-A iam detach-role-policy --role-name "$Name-execution-role" --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy | Out-Null
Try-A iam delete-role --role-name "$Name-execution-role" | Out-Null
Write-Host "`ndone - verify in the console that nothing named '$Name' remains."
