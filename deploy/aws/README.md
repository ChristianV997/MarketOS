# AWS standby deployment

Provisions the AWS half of the PC/AWS pair described in `docs/OPERATIONS.md`:
one `t3.small` EC2 instance that stays in standby (blocked in
`orchestrator.main._await_takeover()`) until the PC's S3 heartbeat goes
stale, plus the S3 bucket that heartbeat lives in.

This is IaC only — nothing here has been applied. Run it yourself against
your own AWS account:

```bash
cd deploy/aws
terraform init
terraform plan     # review what it would create
terraform apply
```

## Before you apply

- **Credentials**: this uses your local AWS credentials (`aws configure` /
  `AWS_PROFILE` / environment variables) — standard Terraform AWS provider
  behavior, nothing project-specific.
- **Cost**: roughly $8-12/month — a `t3.small` (~$15/mo on-demand, but this
  instance is usually idle in standby) + a near-empty S3 bucket + a free-tier
  CloudWatch alarm. Stop/terminate it if you're just testing.
- **SSH is off by default.** Set `ssh_key_name` (an existing EC2 key pair)
  and optionally narrow `ssh_allowed_cidr` if you want shell access; leave
  both alone and the security group has zero inbound rules.

## After you apply

1. **Upload your real `.env`** — the instance never gets your credentials
   baked into its AMI or Terraform state; it fetches `.env` from S3 at boot.
   `terraform output config_upload_command` prints the exact command:
   ```bash
   aws s3 cp /path/to/your/.env s3://<bucket-from-output>/config/marketos.env
   ```
   Until you do this, the container runs with defaults only (harmless —
   it's standby, not ticking yet).

2. **Point your PC at the same bucket.** On the PC (primary), set in `.env`:
   ```
   MARKETOS_HEARTBEAT_BUCKET=<bucket-from-output>
   MARKETOS_NODE_NAME=pc
   ```
   The PC's orchestrator (already running via `scripts/install_daemon.sh`)
   pushes a heartbeat to this bucket on every checkpoint automatically —
   no separate process to run. `pip install boto3` if you haven't (optional
   dependency, see `requirements.txt`).

3. **Verify the pairing**: `terraform output instance_public_ip`, then
   (if you set an SSH key) `ssh ec2-user@<ip>` and `docker logs -f
   marketos-orchestrator` — you should see repeated
   `orchestrator_standby_waiting` log lines. Stop the PC daemon and, after
   `AWS_TAKEOVER_AFTER_S` (default 300s), the AWS instance should log
   `orchestrator_standby_taking_over` and start ticking. Restart the PC
   daemon and confirm the AWS side does *not* also keep ticking afterward —
   today's implementation takes over once and stays active; going back to
   standby on PC recovery is a manual `docker restart marketos-orchestrator`
   on the AWS instance, not automatic. Treat that as a known limitation,
   not a guarantee of hands-off failback.

## What this does NOT do

- No automatic image registry / CI publish pipeline — the instance clones
  the repo and `docker build`s on boot (a few minutes on first launch).
- No state/checkpoint replication from the PC — only a liveness heartbeat.
  If AWS takes over, it starts from its own `state/` (empty unless you seed
  it), not the PC's accumulated state. Full state sync is future work.
- No automatic failback to the PC once AWS has taken over (see step 3).
