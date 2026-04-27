#!/usr/bin/env bash
# Provision the AWS resources the dora GitHub Actions S3 variant needs:
# IAM OIDC provider, S3 bucket (+ CORS, public-read policy), IAM role + policy.
# OIDC-only. Idempotent. See docs/superpowers/specs/2026-04-27-aws-setup-script-design.md.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: setup-aws.sh --repo OWNER/NAME --region REGION (--bucket NAME | --existing-bucket NAME) [options]

Required:
  --repo OWNER/NAME           GitHub repo allowed to assume the role.
  --region REGION             AWS region for the bucket.
  --bucket NAME               Bucket to create (mutually exclusive with --existing-bucket).
  --existing-bucket NAME      Reuse an existing bucket; only configure IAM.

Options:
  --branch NAME               Restrict trust policy to refs/heads/NAME (recommended: main).
                              Default: any ref.
  --role-name NAME            IAM role name. Default: dora-report-uploader.
  -h, --help                  Show this help.

See README "S3 variant" or docs/superpowers/specs/2026-04-27-aws-setup-script-design.md.
EOF
}

# --- Argument parsing ------------------------------------------------------

repo=""
region=""
bucket=""
existing_bucket=""
branch=""
role_name="dora-report-uploader"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)             repo="$2"; shift 2 ;;
    --region)           region="$2"; shift 2 ;;
    --bucket)           bucket="$2"; shift 2 ;;
    --existing-bucket)  existing_bucket="$2"; shift 2 ;;
    --branch)           branch="$2"; shift 2 ;;
    --role-name)        role_name="$2"; shift 2 ;;
    -h|--help)          usage; exit 0 ;;
    *) echo "error: unknown flag: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# --- Validation ------------------------------------------------------------

die() { echo "error: $*" >&2; exit 2; }

[[ -n "$repo"   ]] || die "--repo is required"
[[ -n "$region" ]] || die "--region is required"

if [[ -n "$bucket" && -n "$existing_bucket" ]] || [[ -z "$bucket" && -z "$existing_bucket" ]]; then
  die "exactly one of --bucket / --existing-bucket is required"
fi

[[ "$repo" =~ ^[^/]+/[^/]+$ ]] || die "--repo must be OWNER/NAME (got: $repo)"

# --- Preflight -------------------------------------------------------------

command -v aws >/dev/null 2>&1 || die "aws CLI not on PATH (install AWS CLI v2)"
command -v jq  >/dev/null 2>&1 || die "jq not on PATH (apt install jq / brew install jq)"

if ! sts_json="$(aws sts get-caller-identity 2>/dev/null)"; then
  die "aws credentials not configured (run 'aws configure' or set AWS_PROFILE)"
fi
account_id="$(echo "$sts_json" | jq -r '.Account')"
[[ -n "$account_id" && "$account_id" != "null" ]] || die "aws sts get-caller-identity returned no account id"
