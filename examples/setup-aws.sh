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

# --- 1. OIDC provider ------------------------------------------------------

oidc_url="https://token.actions.githubusercontent.com"
oidc_arn_suffix="oidc-provider/token.actions.githubusercontent.com"

echo "→ checking IAM OIDC provider for $oidc_url" >&2
existing_oidc="$(
  aws iam list-open-id-connect-providers \
    | jq -r ".OpenIDConnectProviderList[].Arn | select(endswith(\"$oidc_arn_suffix\"))"
)"

if [[ -n "$existing_oidc" ]]; then
  echo "✓ OIDC provider already exists, reusing: $existing_oidc" >&2
  oidc_provider_arn="$existing_oidc"
else
  echo "→ creating OIDC provider" >&2
  oidc_provider_arn="$(
    aws iam create-open-id-connect-provider \
      --url "$oidc_url" \
      --client-id-list "sts.amazonaws.com" \
      | jq -r '.OpenIDConnectProviderArn'
  )"
  echo "✓ OIDC provider created: $oidc_provider_arn" >&2
fi

# --- 2. S3 bucket ----------------------------------------------------------

if [[ -n "$existing_bucket" ]]; then
  bucket_name="$existing_bucket"
  echo "→ using existing bucket: $bucket_name (skipping create / CORS / public-policy)" >&2
else
  bucket_name="$bucket"
  echo "→ checking bucket: s3://$bucket_name" >&2

  # head-bucket: exit 0 = exists & ours, non-zero = absent OR not ours.
  # We accept the simplification: if head-bucket succeeds, reuse; otherwise create.
  # If create-bucket then fails because someone else owns the name globally,
  # AWS returns BucketAlreadyExists / BucketAlreadyOwnedByYou which we surface verbatim.
  if aws s3api head-bucket --bucket "$bucket_name" 2>/dev/null; then
    echo "✓ bucket already exists, reusing" >&2
  else
    echo "→ creating bucket" >&2
    if [[ "$region" == "us-east-1" ]]; then
      aws s3api create-bucket --bucket "$bucket_name" --region "$region" >/dev/null
    else
      aws s3api create-bucket \
        --bucket "$bucket_name" \
        --region "$region" \
        --create-bucket-configuration "LocationConstraint=$region" \
        >/dev/null
    fi
    echo "✓ bucket created" >&2
  fi

  echo "→ configuring Block Public Access (allow bucket policies, deny ACLs)" >&2
  aws s3api put-public-access-block \
    --bucket "$bucket_name" \
    --public-access-block-configuration \
      "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=false,RestrictPublicBuckets=false" \
    >/dev/null

  echo "→ applying CORS config" >&2
  aws s3api put-bucket-cors \
    --bucket "$bucket_name" \
    --cors-configuration '{
      "CORSRules": [{
        "AllowedOrigins": ["*"],
        "AllowedMethods": ["GET"],
        "AllowedHeaders": ["*"]
      }]
    }' \
    >/dev/null

  echo "→ applying bucket policy: public read on dora-report.json only" >&2
  bucket_policy="$(jq -nc \
    --arg bucket "$bucket_name" \
    '{
      Version: "2012-10-17",
      Statement: [{
        Sid: "PublicReadDoraReport",
        Effect: "Allow",
        Principal: "*",
        Action: "s3:GetObject",
        Resource: "arn:aws:s3:::\($bucket)/dora-report.json"
      }]
    }')"
  aws s3api put-bucket-policy --bucket "$bucket_name" --policy "$bucket_policy" >/dev/null
fi

# --- 5. IAM role + trust policy --------------------------------------------

if [[ -n "$branch" ]]; then
  sub_pattern="repo:$repo:ref:refs/heads/$branch"
else
  sub_pattern="repo:$repo:*"
  echo "  note: no --branch given; trust matches any ref. Recommend --branch main for production." >&2
fi

trust_policy="$(jq -nc \
  --arg acct "$account_id" \
  --arg sub "$sub_pattern" \
  '{
    Version: "2012-10-17",
    Statement: [{
      Effect: "Allow",
      Principal: { Federated: "arn:aws:iam::\($acct):oidc-provider/token.actions.githubusercontent.com" },
      Action: "sts:AssumeRoleWithWebIdentity",
      Condition: {
        StringEquals: { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
        StringLike:   { "token.actions.githubusercontent.com:sub": $sub }
      }
    }]
  }')"

echo "→ checking IAM role: $role_name" >&2
if aws iam get-role --role-name "$role_name" >/dev/null 2>&1; then
  echo "→ updating existing role's trust policy" >&2
  aws iam update-assume-role-policy \
    --role-name "$role_name" \
    --policy-document "$trust_policy" \
    >/dev/null
else
  echo "→ creating role" >&2
  aws iam create-role \
    --role-name "$role_name" \
    --assume-role-policy-document "$trust_policy" \
    --description "Used by GitHub Actions to upload dora reports for $repo" \
    >/dev/null
fi
role_arn="arn:aws:iam::${account_id}:role/${role_name}"
echo "✓ role ready: $role_arn" >&2

# --- 6. Inline IAM policy --------------------------------------------------

echo "→ applying inline S3 policy to role" >&2
inline_policy="$(jq -nc \
  --arg bucket "$bucket_name" \
  '{
    Version: "2012-10-17",
    Statement: [{
      Effect: "Allow",
      Action: ["s3:GetObject", "s3:PutObject"],
      Resource: [
        "arn:aws:s3:::\($bucket)/dora.db",
        "arn:aws:s3:::\($bucket)/dora-report.json"
      ]
    }]
  }')"
aws iam put-role-policy \
  --role-name "$role_name" \
  --policy-name "dora-s3-access" \
  --policy-document "$inline_policy" \
  >/dev/null
echo "✓ inline S3 policy applied" >&2
