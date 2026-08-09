output "instance_id" {
  value = aws_instance.standby.id
}

output "instance_public_ip" {
  value = aws_instance.standby.public_ip
}

output "heartbeat_bucket" {
  value = aws_s3_bucket.heartbeat.bucket
}

output "config_upload_command" {
  description = "Run this once (with your real .env filled in) before the standby instance can do anything beyond ticking on defaults."
  value       = "aws s3 cp /path/to/your/.env s3://${aws_s3_bucket.heartbeat.bucket}/config/marketos.env --region ${var.aws_region}"
}
