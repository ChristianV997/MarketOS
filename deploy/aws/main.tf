terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ── S3 bucket: heartbeat object + operator-uploaded .env config ────────────────
# One bucket serves both jobs: backend/aws/heartbeat.py reads/writes the
# heartbeat object here, and this instance's user_data fetches its .env
# from config/marketos.env in the same bucket. No checkpoint/state backup
# is wired up yet — the standby only needs liveness + config, not the PC's
# full state snapshot (see docs/OPERATIONS.md's Compute topology section).
resource "random_id" "bucket_suffix" {
  count       = var.heartbeat_bucket_name == "" ? 1 : 0
  byte_length = 4
}

locals {
  bucket_name = var.heartbeat_bucket_name != "" ? var.heartbeat_bucket_name : "marketos-standby-${random_id.bucket_suffix[0].hex}"
}

resource "aws_s3_bucket" "heartbeat" {
  bucket = local.bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "heartbeat" {
  bucket                  = aws_s3_bucket.heartbeat.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "heartbeat" {
  bucket = aws_s3_bucket.heartbeat.id
  versioning_configuration {
    status = "Enabled"
  }
}

# ── IAM: instance can only touch this one bucket ────────────────────────────────
data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "standby" {
  name               = "marketos-standby-${local.bucket_name}"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
  tags               = var.tags
}

data "aws_iam_policy_document" "bucket_access" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:HeadObject"]
    resources = ["${aws_s3_bucket.heartbeat.arn}/*"]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.heartbeat.arn]
  }
}

resource "aws_iam_role_policy" "bucket_access" {
  name   = "marketos-standby-bucket-access"
  role   = aws_iam_role.standby.id
  policy = data.aws_iam_policy_document.bucket_access.json
}

resource "aws_iam_instance_profile" "standby" {
  name = "marketos-standby-${local.bucket_name}"
  role = aws_iam_role.standby.name
}

# ── Security group: no inbound by default; outbound only ───────────────────────
resource "aws_security_group" "standby" {
  name        = "marketos-standby"
  description = "MarketOS AWS standby instance — outbound only unless SSH is explicitly enabled"
  tags        = var.tags

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  dynamic "ingress" {
    for_each = var.ssh_key_name != "" ? [1] : []
    content {
      description = "SSH (only present when ssh_key_name is set)"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [var.ssh_allowed_cidr]
    }
  }
}

# ── Latest Amazon Linux 2023 AMI ────────────────────────────────────────────────
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ── The standby instance itself ─────────────────────────────────────────────────
resource "aws_instance" "standby" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  iam_instance_profile   = aws_iam_instance_profile.standby.name
  vpc_security_group_ids = [aws_security_group.standby.id]
  key_name               = var.ssh_key_name != "" ? var.ssh_key_name : null

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    repo_url    = var.repo_url
    repo_branch = var.repo_branch
    bucket_name = local.bucket_name
    aws_region  = var.aws_region
  })

  # user_data changes (e.g. a new repo_branch) should reprovision the
  # instance rather than silently leaving the old build running.
  user_data_replace_on_change = true

  tags = merge(var.tags, { Name = "marketos-standby" })
}

# ── Alarm: instance-level status check failure ──────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "status_check_failed" {
  alarm_name          = "marketos-standby-status-check-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods   = 2
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "MarketOS AWS standby instance failed its status check."
  dimensions = {
    InstanceId = aws_instance.standby.id
  }
  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  tags          = var.tags
}
