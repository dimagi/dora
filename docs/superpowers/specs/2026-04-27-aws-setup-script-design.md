# `setup-aws.sh`: one-command AWS provisioning for the S3 variant

**Date:** 2026-04-27
**Status:** Draft — pending review

## Goal

Adopters running dora's GitHub Actions workflow with the S3 variant currently
need to provision five AWS resources by hand, following inline comments in
`examples/workflows/dora-report.yml`: an IAM OIDC identity provider, an S3
bucket, bucket CORS, an IAM role with a repo-scoped trust policy, and an inline
S3 policy. The README + workflow comments describe the shapes, but every team
re-derives the same JSON, hand-edits ARNs, and discovers the same gotchas
(BlockPublicAccess settings, region-specific `create-bucket` syntax) on their
own.

Add `examples/setup-aws.sh` — a single bash script that provisions the same
resources in one command, idempotently, using only the AWS CLI and `jq`. The
script's output ends with a paste-ready summary of the role ARN, region, and
bucket name to drop into the adopter's workflow.

## Non-goals

- **Long-lived access keys.** OIDC is the recommended path; teams without OIDC
  access on the AWS side continue to follow the manual fallback documented in
  the README. Automating the access-key flow doubles the script's surface area
  for a small minority of users and would print raw secrets to stdout.
- **A `--destroy` mode.** YAGNI for a one-time bootstrap. Teams that want to
  undo can `aws iam delete-role` etc. by hand.
- **Configuration of an IaC tool** (Terraform, CloudFormation, CDK). Bash +
  AWS CLI keeps the artifact close to the workflow YAML it complements and
  doesn't pull adopters into a new toolchain just to provision a bucket.
- **Multi-bucket / multi-account setups.** The script targets a single bucket
  in a single account, matching the workflow's shape.
- **A `dora setup-aws` Python subcommand.** The work is AWS-side, not
  dora-side; tying it to `dora` would force adopters into a Python venv before
  they can provision.

## Approach

### File layout

- `examples/setup-aws.sh` — new, executable, ~200 lines.
- `examples/workflows/dora-report.yml` — minor edit: drop `--public-read` from
  the documented `dora upload` line in the S3-variant comments, add a one-line
  pointer to the script.
- `README.md` § *S3 variant* — replace the manual "Setup is two AWS resources:
  …" paragraph with a pointer to the script. Long-lived-access-keys section
  unchanged.

### Invocation

```bash
# Fresh setup (creates bucket, CORS, public-read policy, OIDC, role)
./examples/setup-aws.sh \
  --repo dimagi/commcare-hq \
  --bucket dora-commcare-hq \
  --region us-east-1

# With branch restriction (recommended for production)
./examples/setup-aws.sh \
  --repo dimagi/commcare-hq \
  --bucket dora-commcare-hq \
  --region us-east-1 \
  --branch main \
  --role-name dora-commcare-hq-uploader

# Reuse an existing bucket (IAM only)
./examples/setup-aws.sh \
  --repo dimagi/commcare-hq \
  --existing-bucket shared-ci-artifacts \
  --region us-east-1
```

### Flags

| Flag | Required | Default | Purpose |
|---|---|---|---|
| `--repo OWNER/NAME` | yes | — | Repo allowed to assume the role. Validated against `^[^/]+/[^/]+$`. |
| `--region REGION` | yes | — | AWS region for the bucket. No default — picking one for the user can land them on an unintended region. |
| `--bucket NAME` | exactly one of `--bucket` / `--existing-bucket` | — | Bucket to create. |
| `--existing-bucket NAME` | exactly one of `--bucket` / `--existing-bucket` | — | Skip bucket creation/CORS/public-read policy; only configure IAM, granting access to this bucket. |
| `--branch NAME` | no | none → trust matches any ref | If set, trust policy locks to `repo:OWNER/NAME:ref:refs/heads/BRANCH`. If unset, uses `repo:OWNER/NAME:*`. The script prints a one-line note recommending `--branch main` when omitted. |
| `--role-name NAME` | no | `dora-report-uploader` | IAM role name. |
| `--help` | no | — | Print flag list, short example, README link. |

**Why no `--branch` default of `main`:** some adopters run the workflow on
`master`, on a release branch, or via `workflow_dispatch` from arbitrary refs
(which `*` covers but `main` does not). Forcing a default would silently
misconfigure those teams.

**Hardcoded (not flags):**

- Object keys: `dora.db` and `dora-report.json`. Match the workflow exactly.
- Inline policy actions: `s3:GetObject`, `s3:PutObject`. No
  `s3:PutObjectAcl` — public read is granted by bucket policy, not by per-
  object ACLs (see *Trade-off* below). Bucket-level `BlockPublicAcls=true`
  would reject ACL writes anyway, so granting `PutObjectAcl` would be misleading.
- Inline policy resource ARNs: scoped to the two specific keys, not
  `bucket/*`.
- CORS config: `AllowedOrigins ["*"]`, `AllowedMethods ["GET"]`,
  `AllowedHeaders ["*"]` — exactly what the README documents.

### Preflight checks

At the top of the script, before any AWS calls:

1. `aws` on PATH.
2. `jq` on PATH.
3. `aws sts get-caller-identity` succeeds (credentials configured). The
   resulting account ID is captured for the trust policy.
4. Flag validation: `--repo` matches `^[^/]+/[^/]+$`, exactly one of
   `--bucket` / `--existing-bucket` provided, etc.

Any failure exits with a clear error pointing at the README.

### Resources, in creation order

The script uses `set -euo pipefail`. Each step checks for existence first;
re-runs are safe.

**1. IAM OIDC identity provider** (`token.actions.githubusercontent.com`)

- Check: `aws iam list-open-id-connect-providers` for an ARN ending in
  `/token.actions.githubusercontent.com`.
- If absent: `aws iam create-open-id-connect-provider --url
  https://token.actions.githubusercontent.com --client-id-list
  sts.amazonaws.com`. AWS no longer requires a thumbprint as of mid-2023;
  rely on built-in cert validation.
- Account-wide; typically created once per AWS account and reused across
  repos. Logs "OIDC provider already exists, reusing" when found.

**2. S3 bucket** (skipped if `--existing-bucket`)

- Check: `aws s3api head-bucket --bucket NAME`. Three outcomes:
  - 200 → bucket exists and we own it → reuse.
  - 403 → bucket exists, owned by someone else → abort with "bucket name taken
    globally, pick another."
  - 404 → create with `aws s3api create-bucket`. Region-aware:
    `us-east-1` omits `LocationConstraint`; other regions include it.
- Block Public Access: set `BlockPublicPolicy=false` and
  `RestrictPublicBuckets=false` so the public-read bucket policy below is
  honoured. Leave `BlockPublicAcls=true` and `IgnorePublicAcls=true` — we use
  a bucket policy, not ACLs, to make `dora-report.json` public. (See
  *Trade-off* below for the implications for the workflow YAML.)

**3. Bucket CORS** (skipped if `--existing-bucket`)

- Always `put-bucket-cors` with the documented config. Idempotent — overwriting
  with the same JSON is a no-op semantically.

**4. Bucket policy granting public read on `dora-report.json`** (skipped if
`--existing-bucket`)

- `put-bucket-policy` with a single statement: `s3:GetObject` for
  `Principal: *` on `arn:aws:s3:::BUCKET/dora-report.json` only — `dora.db`
  remains private. Idempotent.

**5. IAM role + inline policy**

- Role check: `aws iam get-role --role-name NAME`.
  - Absent → `create-role` with the trust policy (subbed with account ID,
    repo, branch).
  - Present → `update-assume-role-policy` to refresh the trust document.
    Handles re-running with a different `--branch` or `--repo`. Logs
    "updating existing role's trust policy."
- Inline policy: always `put-role-policy` with the S3 statement. Idempotent.

**Order rationale:** OIDC provider first (the role's trust policy references
its ARN). Bucket before role inline policy (so the ARN we grant access to
actually exists, though IAM doesn't enforce this). Trust policy update last
so any earlier failure leaves no role pointing at half-built infra.

### Trust policy template

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::<ACCT>:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
      },
      "StringLike": {
        "token.actions.githubusercontent.com:sub": "<SUB_PATTERN>"
      }
    }
  }]
}
```

`<SUB_PATTERN>` is `repo:OWNER/REPO:ref:refs/heads/BRANCH` if `--branch` is
given, otherwise `repo:OWNER/REPO:*`.

### Inline S3 policy template

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:PutObject"],
    "Resource": [
      "arn:aws:s3:::BUCKET/dora.db",
      "arn:aws:s3:::BUCKET/dora-report.json"
    ]
  }]
}
```

### Bucket policy template

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "PublicReadDoraReport",
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::BUCKET/dora-report.json"
  }]
}
```

### Output

Progress on stderr, paste-ready summary on stdout — so adopters can `2>/dev/null`
to capture only the summary. Final block:

```
─────────────────────────────────────────────────
AWS setup complete.

Bucket:   dora-commcare-hq (us-east-1)
Role ARN: arn:aws:iam::123456789012:role/dora-report-uploader

In your dora-report.yml workflow, set:
  role-to-assume: arn:aws:iam::123456789012:role/dora-report-uploader
  aws-region:     us-east-1
  bucket:         dora-commcare-hq

Public dashboard URL once the workflow runs:
  https://dimagi.github.io/dora/?url=https://dora-commcare-hq.s3.us-east-1.amazonaws.com/dora-report.json
─────────────────────────────────────────────────
```

The `--existing-bucket` path prints the same block but with a note that CORS
and public-read policy on the existing bucket are the user's responsibility.

No secrets in output — OIDC means no access keys to print.

## Trade-offs

### Bucket policy vs object ACL for public read

The example workflow currently uses `dora upload --public-read`, which sets a
`public-read` ACL on the uploaded `dora-report.json`. This requires the bucket
to have ACLs enabled (`ObjectOwnership = BucketOwnerPreferred`) and certain
Block Public Access settings disabled.

The script switches the public-read mechanism to a **bucket policy** scoped to
`dora-report.json` only. Why:

- AWS now defaults new buckets to `BucketOwnerEnforced`, which disables ACLs
  outright. A script that relied on ACLs would need to flip ownership back —
  going against AWS's current direction.
- The bucket policy is explicit about what's public (one named key) rather
  than relying on per-object ACL state, which is harder to audit.
- Block Public Access settings still need adjustment either way; the bucket
  policy needs `BlockPublicPolicy=false`/`RestrictPublicBuckets=false`, the
  ACL path needs `BlockPublicAcls=false`/`IgnorePublicAcls=false`. Roughly
  equivalent.

**Implication:** the workflow's `--public-read` flag becomes redundant. Drop
it from the documented `dora upload` line in `examples/workflows/dora-report.yml`
as part of this change. Adopters who copied the old workflow before this change
will see their `--public-read` upload fail at the bucket-policy level
(`BlockPublicAcls=true` rejects public ACL writes); the fix is to update their
workflow YAML — clearly signposted in the README change.

### `--branch` default

Defaulting `--branch` to `main` would match the workflow comments verbatim and
save adopters one keystroke, but silently locks out teams on `master`, release
branches, or `workflow_dispatch` from feature branches. Defaulting to `*`
(any ref) is permissive enough to work but trains adopters to skip the
restriction. Compromise: no default, but recommend `--branch main` in the
log line emitted when the flag is omitted.

### Idempotency cost

Each "exists?" check is one extra AWS API call per resource. For five
resources that's five extra calls on a re-run — negligible. The cost is
~30 lines of conditional logic in the script. Worth it: a one-time bootstrap
that fails partway through (network blip, MFA timeout, insufficient
permissions) is a frustrating place to be without retry support.

## Risks

- **Bucket name collisions** are global. Script aborts cleanly on 403 from
  `head-bucket` (someone else owns it), but adopters may still try common
  names like `dora-reports` and bounce a few times.
- **Region mismatches.** A team picks `us-east-1` for the bucket but the
  workflow uses `us-west-2` — the role works but `dora upload` 301-redirects.
  Mitigation: the summary block prints the region, and the workflow's
  `aws-region` setting is shown next to it for visual diff.
- **Trust policy too narrow.** A team passes `--branch main` then later runs
  the workflow on `release/2026.04`. Mitigation: re-running the script with
  the new branch updates the trust policy in place. We document this in the
  script's `--help`.
- **AWS API changes.** OIDC thumbprint requirement was removed in 2023; if
  AWS reintroduces it, the `create-open-id-connect-provider` call breaks.
  Low likelihood; documented in a code comment.

## Out of scope / future work

- Provisioning the access-keys fallback (see *Non-goals*).
- A `--destroy` flag.
- A CloudFormation / Terraform equivalent for teams that prefer IaC.
- Per-environment buckets (staging vs prod). Adopters who want that run the
  script multiple times with different `--bucket` values; that already works.
- Logging / CloudTrail tagging on the created resources.
