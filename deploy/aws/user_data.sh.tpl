#!/bin/bash
# Rendered by Terraform (deploy/aws/main.tf) — provisions this instance as
# the AWS standby half of the PC/AWS pair described in docs/OPERATIONS.md.
# Builds the image from source on boot rather than pulling from a registry —
# there is no publish pipeline for this repo, and building here keeps the
# whole standby path to "one git clone + one docker build", no extra infra.
set -euo pipefail
exec > >(tee /var/log/marketos-userdata.log) 2>&1

echo "marketos user_data starting at $(date -u)"

if command -v dnf >/dev/null 2>&1; then
    dnf install -y docker git unzip
elif command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y docker.io git unzip
else
    echo "fatal: neither dnf nor apt-get found on this AMI" >&2
    exit 1
fi
systemctl enable --now docker

# AWS CLI v2 — installed from the official bundle rather than a distro
# package, since package availability/naming varies across base AMIs.
if ! command -v aws >/dev/null 2>&1; then
    curl -fsS "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
    unzip -q /tmp/awscliv2.zip -d /tmp
    /tmp/aws/install
fi

REPO_DIR=/opt/marketos
if [ ! -d "$REPO_DIR" ]; then
    git clone --branch "${repo_branch}" --depth 1 "${repo_url}" "$REPO_DIR"
fi
cd "$REPO_DIR"

# Real secrets are never baked into the AMI or this script: upload a real
# .env once, out-of-band, to this bucket (see deploy/aws/README.md). The
# instance's IAM role only grants access to this one bucket.
if aws s3 cp "s3://${bucket_name}/config/marketos.env" "$REPO_DIR/.env" --region "${aws_region}"; then
    echo "loaded config/marketos.env from s3://${bucket_name}"
else
    echo "warning: no config/marketos.env found in s3://${bucket_name} yet — container starts with defaults only"
    touch "$REPO_DIR/.env"
fi

docker build -t marketos:standby .

docker rm -f marketos-orchestrator >/dev/null 2>&1 || true
docker run -d --name marketos-orchestrator \
    --restart unless-stopped \
    --env-file "$REPO_DIR/.env" \
    -e ORCHESTRATOR_STANDBY=true \
    -e MARKETOS_NODE_NAME=aws \
    -e MARKETOS_HEARTBEAT_BUCKET="${bucket_name}" \
    -e AWS_DEFAULT_REGION="${aws_region}" \
    marketos:standby \
    python -m orchestrator.main

echo "marketos user_data finished at $(date -u)"
