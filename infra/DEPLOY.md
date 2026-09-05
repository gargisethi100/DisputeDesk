# Deploy — ECS Fargate (us-east-1), 2-hour cap

One container, one Streamlit process, model calls go to Bedrock via the **task role**
(no keys in the image or env). Fallback if the cap is hit: Streamlit Community Cloud in mock mode.

## 0. Local check (mock mode)
```bash
docker build -t disputedesk .
docker run --rm -p 8501:8501 disputedesk            # http://localhost:8501
docker run --rm disputedesk python -m pytest -q     # tests inside the image
```

## 1. Push to ECR
```bash
export AWS_REGION=us-east-1 ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr create-repository --repository-name disputedesk
aws ecr get-login-password | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
docker tag disputedesk:latest $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/disputedesk:latest
docker push $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/disputedesk:latest
```

## 2. IAM — two roles, least privilege
```bash
# execution role: pull image + write logs (AWS managed policy)
aws iam create-role --role-name disputedesk-execution-role --assume-role-policy-document file://infra/ecs-trust.json
aws iam attach-role-policy --role-name disputedesk-execution-role --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# task role: invoke ONE Bedrock model, nothing else
sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" infra/task-role-policy.json > /tmp/task-policy.json
aws iam create-role --role-name disputedesk-task-role --assume-role-policy-document file://infra/ecs-trust.json
aws iam put-role-policy --role-name disputedesk-task-role --policy-name bedrock-invoke-one-model --policy-document file:///tmp/task-policy.json
```
`infra/ecs-trust.json` is the standard `ecs-tasks.amazonaws.com` trust policy.

Enable model access for the chosen Claude model in the Bedrock console for us-east-1 first.

## 3. Cluster, task, service, ALB
```bash
aws ecs create-cluster --cluster-name disputedesk
sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" infra/ecs-task-definition.json > /tmp/taskdef.json
aws ecs register-task-definition --cli-input-json file:///tmp/taskdef.json
```
Console (fastest within the cap): create an **Application Load Balancer** (internet-facing, HTTP:80),
target group `ip` type on port **8501**, health check path **`/_stcore/health`**. Then create the ECS
service: launch type Fargate, task `disputedesk`, desired count 1, private subnets if you have a NAT
(else public subnets + public IP), security group allowing 8501 **from the ALB SG only**, attach the
target group. Streamlit uses WebSockets — ALB supports them; keep the idle timeout ≥ 120 s.

## 4. Smoke
```bash
curl -s http://<alb-dns>/_stcore/health     # ok
aws logs tail /ecs/disputedesk --follow
```
Open the ALB URL, run DSP001 → approve, DSP009 → flagged. If Bedrock errors, check the task-role
policy ARN matches `BEDROCK_MODEL_ID` exactly.

## Deferred to production (documented, not built)
Auth + roles (ALB → Cognito/OIDC; analyst vs approver), HTTPS via ACM, private subnets with the ALB as
the only public surface, Secrets Manager for the gateway API key, retries/timeouts/rate limits on model
and API calls, Postgres checkpointer + audit table replacing in-memory/JSONL, WAF on the ALB.

## Fallback — Streamlit Community Cloud (mock mode)
Connect the public repo, main file `app.py`, secrets: `DISPUTEDESK_LLM_PROVIDER=mock`. No AWS needed;
the demo path is identical. Record the Loom against this if the ECS URL is not stable.
