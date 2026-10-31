# Respinning the custom-VPC AWS setup (RDS + ElastiCache + S3 + VPC)

This is the exact sequence used to build the custom-VPC deployment
(documented in `NOTES/reservly-aws-services-deployment.md`), written down
so it can be rebuilt quickly later without rediscovering parameters from
scratch. The templates themselves (`vpc.yaml`, `aws-services-demo.yaml`,
`ec2-secrets-role.yaml`) are unchanged and already in this folder — this
file is the missing piece: the actual commands and parameter values used
to deploy them, in order.

**Torn down on 2026-10-24** to stop the ~$40/month cost while not actively
needed for an interview. Everything below rebuilds it from scratch.

---

## 0. Prerequisites

- AWS CLI v2 on PATH (the per-user install, not the stale per-machine one):
  `export PATH="/c/Users/archi/AppData/Local/Programs/Amazon/AWSCLIV2:$PATH"`
- `deploy-bot` IAM user needs these policies attached (all were added
  incrementally last time — see `NOTES/AWS Deployment/reservly-cloudformation-bugs.md`
  Bug 3 for why): `AmazonVPCFullAccess`, `AmazonEC2FullAccess`,
  `AWSCloudFormationFullAccess`, `SecretsManagerReadWrite`, and an inline
  policy `EC2SecretsRoleManagement` scoped to `reservly-*` IAM
  roles/instance-profiles (JSON for that one is in the chat history /
  `reservly-cloudformation-bugs.md` if it needs recreating).
- SSH key: `~/.ssh/reservation-system-key.pem`, key pair name
  `reservation-system-key`.
- Elastic IP already exists and is reused, not recreated:
  `eipalloc-0d4f0e37070ad2225` (public IP `13.206.34.52`) — DNS already
  points here permanently, so respinning never needs a DNS change, only
  re-association.

---

## 1. Deploy the VPC

```bash
aws cloudformation create-stack \
  --stack-name reservly-vpc \
  --template-body file://infra/vpc.yaml \
  --region ap-south-1
aws cloudformation wait stack-create-complete --stack-name reservly-vpc --region ap-south-1
aws cloudformation describe-stacks --stack-name reservly-vpc --region ap-south-1 --query "Stacks[0].Outputs"
```
Note the outputs: `VpcId`, `PublicSubnetIds` (comma list), `PrivateSubnetIds`
(comma list), `PublicSubnetAId`, `EC2SecurityGroupId`. Used in every step below.

## 2. Deploy RDS + ElastiCache + S3 into that VPC

```bash
aws cloudformation create-stack \
  --stack-name reservly-aws-services-v2 \
  --template-body file://infra/aws-services-demo.yaml \
  --parameters \
    ParameterKey=VpcId,ParameterValue=<VpcId from step 1> \
    ParameterKey=SubnetIds,ParameterValue="<PrivateSubnetIds from step 1, comma-escaped as X\,Y>" \
    ParameterKey=AppSecurityGroupId,ParameterValue=<EC2SecurityGroupId from step 1> \
  --region ap-south-1
aws cloudformation wait stack-create-complete --stack-name reservly-aws-services-v2 --region ap-south-1
aws cloudformation describe-stacks --stack-name reservly-aws-services-v2 --region ap-south-1 --query "Stacks[0].Outputs"
```
Note: `RDSEndpointAddress`, `RDSSecretArn`, `CacheEndpointAddress`,
`FrontendBucketName`, `FrontendWebsiteURL`.

**If this fails with a Secrets Manager permission error**, `deploy-bot`
needs `SecretsManagerReadWrite` (RDS needs permission to *create* the
auto-generated password secret on your behalf — see prerequisites above).

## 3. Deploy the IAM role scoped to the new RDS secret

```bash
aws cloudformation create-stack \
  --stack-name reservly-ec2-secrets-role-v2 \
  --template-body file://infra/ec2-secrets-role.yaml \
  --parameters ParameterKey=RDSSecretArn,ParameterValue="<RDSSecretArn from step 2>" \
  --capabilities CAPABILITY_IAM \
  --region ap-south-1
aws cloudformation wait stack-create-complete --stack-name reservly-ec2-secrets-role-v2 --region ap-south-1
aws cloudformation describe-stacks --stack-name reservly-ec2-secrets-role-v2 --region ap-south-1 --query "Stacks[0].Outputs"
```
Note: `InstanceProfileName`.

## 4. Launch the EC2 instance in the new VPC's public subnet

```bash
aws ec2 run-instances \
  --image-id ami-07dfe2c11d33a069a \
  --instance-type t3.micro \
  --key-name reservation-system-key \
  --subnet-id <PublicSubnetAId from step 1> \
  --security-group-ids <EC2SecurityGroupId from step 1> \
  --iam-instance-profile Name=<InstanceProfileName from step 3> \
  --associate-public-ip-address \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=reservly-ec2-v2}]' \
  --region ap-south-1
```
Wait for `running`, note the new instance's public IP.

## 5. Provision the instance (Docker, app code, certs)

```bash
# Install Docker
ssh -i ~/.ssh/reservation-system-key.pem ubuntu@<new-ip> "curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker ubuntu"

# Copy app directory + Let's Encrypt certs from wherever the app currently
# lives (the old instance, or a fresh git clone if nothing else is live)
ssh -i ~/.ssh/reservation-system-key.pem ubuntu@<source> "tar czf - -C /home/ubuntu app" | ssh -i ~/.ssh/reservation-system-key.pem ubuntu@<new-ip> "tar xzf - -C /home/ubuntu"
ssh -i ~/.ssh/reservation-system-key.pem ubuntu@<source> "sudo tar czf - -C /etc letsencrypt" | ssh -i ~/.ssh/reservation-system-key.pem ubuntu@<new-ip> "sudo tar xzf - -C /etc"

# Install AWS CLI v2 on the instance itself (needed to fetch the RDS secret)
ssh -i ~/.ssh/reservation-system-key.pem ubuntu@<new-ip> "cd /tmp && curl -s 'https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip' -o awscliv2.zip && sudo apt-get update -qq && sudo apt-get install -y -qq unzip && unzip -q awscliv2.zip && sudo ./aws/install"
```

## 6. Point the app at the new RDS/ElastiCache, fetch the password safely

**Use Python for the in-place edit, never `sed`** — a prior respin
corrupted the password and leaked a fragment of it via a `sed` delimiter
collision (full story: `NOTES/AWS Deployment/reservly-cloudformation-bugs.md`
Bug 3). Run this entirely over SSH so the password never enters the local
terminal/Claude's context:

```bash
ssh -i ~/.ssh/reservation-system-key.pem ubuntu@<new-ip> '
set -e
cd ~/app/backend
cp .env .env.bak-$(date +%s)
PASSWORD=$(/usr/local/bin/aws secretsmanager get-secret-value --secret-id "<RDSSecretArn>" --region ap-south-1 --query SecretString --output text | python3 -c "import json,sys; print(json.load(sys.stdin)[\"password\"])")
python3 - "$PASSWORD" <<"PYEOF"
import sys
new_val = sys.argv[1]
with open(".env") as f:
    lines = f.readlines()
with open(".env", "w") as f:
    for line in lines:
        f.write(line if not line.startswith("POSTGRES_PASSWORD=") else "POSTGRES_PASSWORD=" + new_val + "\n")
PYEOF
sed -i "s|^POSTGRES_HOST=.*|POSTGRES_HOST=<RDSEndpointAddress>|" .env
sed -i "s|^POSTGRES_PORT=.*|POSTGRES_PORT=5432|" .env
sed -i "s|^REDIS_URL=.*|REDIS_URL=redis://<CacheEndpointAddress>:6379/0|" .env
unset PASSWORD
echo "ENV UPDATED"
'
```
(`sed` is fine for the host/port/URL lines above — they're not random
secrets, so there's no delimiter-collision risk; it's specifically the
password that needs the Python approach.)

Update `nginx.aws-services.conf` to point at the new S3 bucket:
```bash
ssh -i ~/.ssh/reservation-system-key.pem ubuntu@<new-ip> '
cd ~/app
sed -i "s|<old-bucket-name>|<FrontendBucketName from step 2>|g" nginx.aws-services.conf
'
```

## 7. Build the frontend and sync it to the new S3 bucket

```bash
# Locally, build the frontend if needed, then from wherever it's built:
scp -i ~/.ssh/reservation-system-key.pem -r ubuntu@<new-ip>:~/app/frontend/dist/* /tmp/reservly-dist/
aws s3 sync /tmp/reservly-dist/ s3://<FrontendBucketName from step 2>/ --region ap-south-1
```

## 8. Bring the stack up and verify

```bash
ssh -i ~/.ssh/reservation-system-key.pem ubuntu@<new-ip> "cd ~/app && docker compose -f docker-compose.prod.aws-services.yml up -d --build"
ssh -i ~/.ssh/reservation-system-key.pem ubuntu@<new-ip> "docker exec app-web-1 python manage.py seed_demo_products && docker exec app-web-1 python manage.py backfill_embeddings"

# Verify before touching DNS/EIP - test via SNI against the new instance's own IP:
curl -s --resolve reservly.architsalriwal.dev:443:<new-ip> https://reservly.architsalriwal.dev/api/products/ -o /dev/null -w "%{http_code}\n"
```

**Known gotcha** (hit last time, see `reservly-cloudformation-bugs.md`
Bug 4): `backend/Dockerfile` now has `mkdir -p /code/staticfiles` before
the `chown` step — this is already fixed in the repo, no action needed,
just don't accidentally revert it.

## 9. Cut over (only once step 8 is fully verified)

```bash
aws ec2 associate-address --allocation-id eipalloc-0d4f0e37070ad2225 --instance-id <new-instance-id> --allow-reassociation --region ap-south-1
curl -s https://reservly.architsalriwal.dev/api/products/ -o /dev/null -w "%{http_code}\n"
```

## 10. Decommission whatever was running before (if anything)

Terminate the old instance and delete its stacks the same way documented
in `NOTES/reservly-aws-services-deployment.md` section 5 — detach instance
profile, empty any S3 bucket before deleting its stack
(`aws s3 rm s3://<bucket>/ --recursive` first, or `delete-stack` fails with
"bucket not empty"), then `delete-stack` for the IAM role stack, the
services stack, and finally the VPC stack (in that order — the VPC can't
delete while anything still lives inside it).

---

## Costs, for reference

~$40/month total while running (EC2 ~$8.18, RDS ~$19, ElastiCache ~$12.41,
S3 ~$0, no NAT Gateway) — see `NOTES/reservly-aws-services-deployment.md`
section 6 for the full breakdown.
