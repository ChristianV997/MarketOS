variable "aws_region" {
  description = "AWS region for the standby instance and S3 bucket."
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance type for the standby orchestrator. t3.small is enough to run the tick loop + API against cloud inference (Ollama is the PC's job, not this instance's)."
  type        = string
  default     = "t3.small"
}

variable "repo_url" {
  description = "Git URL the instance clones and builds on boot (no container registry required)."
  type        = string
  default     = "https://github.com/ChristianV997/MarketOS.git"
}

variable "repo_branch" {
  description = "Branch/ref to check out on the standby instance."
  type        = string
  default     = "main"
}

variable "heartbeat_bucket_name" {
  description = "Globally-unique S3 bucket name for the PC/AWS heartbeat object and the .env config the standby instance boots with. Leave the default and let random_id make it unique, or set your own."
  type        = string
  default     = ""
}

variable "ssh_key_name" {
  description = "Existing EC2 key pair name for SSH access (optional — leave empty to disable SSH entirely)."
  type        = string
  default     = ""
}

variable "ssh_allowed_cidr" {
  description = "CIDR allowed to SSH in, only used if ssh_key_name is set. Narrow this to your own IP — 0.0.0.0/0 is not a safe default for a real deployment."
  type        = string
  default     = "0.0.0.0/0"
}

variable "alarm_sns_topic_arn" {
  description = "Optional SNS topic ARN to notify on EC2 status-check-failed. Leave empty to skip notifications (the alarm still exists, just with no action)."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Common tags applied to every resource."
  type        = map(string)
  default = {
    Project = "marketos"
    Role    = "aws-standby"
  }
}
