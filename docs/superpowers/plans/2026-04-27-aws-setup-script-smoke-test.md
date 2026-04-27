# `setup-aws.sh` Manual Smoke Test

Run this against a real AWS test account before merging changes to the
script. Unit tests stub `aws`; this exercises the actual API contract.

## Setup

- An AWS account where you have IAM + S3 admin permissions.
- A test repo (yours, doesn't need to be a fork of dora — the trust policy
  references it but no real workflow needs to run).
- `aws configure sso` (or env vars) targeting the test account.

## 1. Fresh setup, no `--branch`

    ./examples/setup-aws.sh \
      --repo your-handle/test-repo \
      --bucket dora-smoketest-$(date +%s) \
      --region us-east-1

Expected:
- Script exits 0.
- Stderr shows: OIDC creating (or reusing), bucket creating, BPA, CORS,
  bucket policy, role creating, inline policy.
- Stderr contains "no --branch given … Recommend --branch main".
- Stdout shows summary block with role ARN, bucket name, dashboard URL.

Verify in the AWS console:
- IAM → Identity providers → token.actions.githubusercontent.com exists.
- IAM → Roles → dora-report-uploader exists with the expected trust policy
  (`StringLike` sub = `repo:your-handle/test-repo:*`) and inline policy
  scoped to two S3 keys.
- S3 → bucket → Permissions → Bucket policy contains the public-read
  statement on dora-report.json.
- S3 → bucket → Permissions → CORS contains the GET-from-* rule.

## 2. Re-run idempotency

Run the same command again. Expected:
- Script exits 0.
- Stderr: "OIDC provider already exists, reusing", "bucket already exists,
  reusing", "role exists; updating existing role's trust policy".

## 3. Branch restriction update

Re-run with `--branch main`:

    ./examples/setup-aws.sh \
      --repo your-handle/test-repo \
      --bucket <same-bucket-as-step-1> \
      --region us-east-1 \
      --branch main

Expected:
- Stderr: "role exists; updating".
- Verify in console: trust policy `StringLike` sub now =
  `repo:your-handle/test-repo:ref:refs/heads/main`.

## 4. `--existing-bucket` mode

    ./examples/setup-aws.sh \
      --repo your-handle/test-repo \
      --existing-bucket <bucket-from-step-1> \
      --region us-east-1

Expected:
- Stderr does NOT include "creating bucket", "applying CORS", "applying
  bucket policy". It DOES include OIDC and IAM steps.
- Stdout summary includes the "--existing-bucket was used … your responsibility"
  caveat.

## 5. Bucket name taken by another owner (403)

Pick a bucket name you know is taken (e.g. `aws`, `s3`):

    ./examples/setup-aws.sh \
      --repo your-handle/test-repo \
      --bucket aws \
      --region us-east-1

Expected:
- Script exits non-zero.
- Stderr surfaces the AWS error verbatim ("BucketAlreadyExists" or similar).

## 6. Cleanup

    aws s3 rb s3://<your-bucket> --force
    aws iam delete-role-policy --role-name dora-report-uploader --policy-name dora-s3-access
    aws iam delete-role --role-name dora-report-uploader
    # Leave the OIDC provider in place — it's account-wide and may be reused.
