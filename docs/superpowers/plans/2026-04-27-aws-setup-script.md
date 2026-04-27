# `setup-aws.sh` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `examples/setup-aws.sh`, a one-command bash script that provisions every AWS resource the dora S3-variant workflow needs (S3 bucket + CORS + public-read bucket policy, IAM OIDC provider, IAM role with repo-scoped trust policy and inline S3 policy), idempotently, OIDC-only.

**Architecture:** Single bash file under `examples/`. Uses `aws` CLI + `jq` (preflight-checked). `set -euo pipefail`. Each AWS resource gets a check-then-create pattern so re-runs converge on the desired state. Trust policy and inline policies are JSON heredocs interpolated with bash variables. Final stdout is a paste-ready summary block. Tests stub the `aws` binary on PATH and assert on its recorded calls.

**Tech stack:** Bash 4+, AWS CLI v2, `jq`. Tests: pytest + subprocess + a fake `aws` stub installed onto a fixture PATH.

**Reference:** The design spec at `docs/superpowers/specs/2026-04-27-aws-setup-script-design.md` is the source of truth. If this plan and the spec disagree, the spec wins — stop and flag.

**Working directory:** All paths are relative to `/home/skelly/src/dora/`.

---

## Task 1: Skeleton + `--help` (TDD: help test first)

**Files:**
- Create: `examples/setup-aws.sh`
- Create: `tests/test_setup_aws.py`
- Create: `tests/conftest_setup_aws.py` (fixtures live alongside the test for clarity; merged into root `conftest.py` in Task 3)

- [ ] **Step 1: Write failing test for `--help`**

In `tests/test_setup_aws.py`:

```python
"""Tests for examples/setup-aws.sh."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "setup-aws.sh"


def test_help_flag_prints_usage_and_exits_zero():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "--repo" in result.stdout
    assert "--bucket" in result.stdout
    assert "--existing-bucket" in result.stdout
    assert "--region" in result.stdout
    assert "--branch" in result.stdout
    assert "--role-name" in result.stdout
```

- [ ] **Step 2: Run test — expect FAIL (script doesn't exist)**

Run: `uv run pytest tests/test_setup_aws.py::test_help_flag_prints_usage_and_exits_zero -v`
Expected: FAIL — `bash: examples/setup-aws.sh: No such file or directory` or similar.

- [ ] **Step 3: Create the script with shebang, strictness, and `--help`**

Create `examples/setup-aws.sh`:

```bash
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
```

Then make it executable:

```bash
chmod +x examples/setup-aws.sh
```

- [ ] **Step 4: Run test — expect PASS**

Run: `uv run pytest tests/test_setup_aws.py::test_help_flag_prints_usage_and_exits_zero -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add examples/setup-aws.sh tests/test_setup_aws.py
git commit -m "feat(setup-aws): scaffold script with --help"
```

---

## Task 2: Argument validation (TDD)

**Files:**
- Modify: `examples/setup-aws.sh` (add validation block after parse loop)
- Modify: `tests/test_setup_aws.py`

- [ ] **Step 1: Add failing tests for each validation rule**

Append to `tests/test_setup_aws.py`:

```python
import pytest


@pytest.mark.parametrize(
    "argv, expected_substr",
    [
        # missing required
        (["--region", "us-east-1", "--bucket", "b"], "--repo is required"),
        (["--repo", "o/n", "--bucket", "b"], "--region is required"),
        (["--repo", "o/n", "--region", "us-east-1"], "exactly one of --bucket / --existing-bucket"),
        # both bucket flags
        (
            ["--repo", "o/n", "--region", "us-east-1", "--bucket", "b", "--existing-bucket", "c"],
            "exactly one of --bucket / --existing-bucket",
        ),
        # malformed --repo
        (
            ["--repo", "no-slash", "--region", "us-east-1", "--bucket", "b"],
            "--repo must be OWNER/NAME",
        ),
        (
            ["--repo", "a/b/c", "--region", "us-east-1", "--bucket", "b"],
            "--repo must be OWNER/NAME",
        ),
    ],
)
def test_argument_validation(argv, expected_substr):
    result = subprocess.run(
        ["bash", str(SCRIPT), *argv],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert expected_substr in result.stderr
```

- [ ] **Step 2: Run tests — expect all FAIL**

Run: `uv run pytest tests/test_setup_aws.py -v -k validation`
Expected: 6 failures (script doesn't validate yet, falls through into preflight which doesn't exist).

- [ ] **Step 3: Add validation block to the script**

Append after the `while [[ $# -gt 0 ]]` loop in `examples/setup-aws.sh`:

```bash
# --- Validation ------------------------------------------------------------

die() { echo "error: $*" >&2; exit 2; }

[[ -n "$repo"   ]] || die "--repo is required"
[[ -n "$region" ]] || die "--region is required"

if [[ -n "$bucket" && -n "$existing_bucket" ]] || [[ -z "$bucket" && -z "$existing_bucket" ]]; then
  die "exactly one of --bucket / --existing-bucket is required"
fi

[[ "$repo" =~ ^[^/]+/[^/]+$ ]] || die "--repo must be OWNER/NAME (got: $repo)"
```

- [ ] **Step 4: Run tests — expect all PASS**

Run: `uv run pytest tests/test_setup_aws.py -v -k validation`
Expected: 6 passes.

- [ ] **Step 5: Commit**

```bash
git add examples/setup-aws.sh tests/test_setup_aws.py
git commit -m "feat(setup-aws): validate required and mutually-exclusive flags"
```

---

## Task 3: Fake-`aws` test fixture + preflight checks

**Files:**
- Modify: `tests/conftest.py` (add `fake_aws` fixture)
- Modify: `examples/setup-aws.sh` (add preflight block)
- Modify: `tests/test_setup_aws.py`

- [ ] **Step 1: Add `fake_aws` fixture to `tests/conftest.py`**

Append to `tests/conftest.py`:

```python
import os
import shutil


@pytest.fixture
def fake_aws(tmp_path, monkeypatch):
    """Stub `aws` CLI on PATH that records its argv and returns canned JSON.

    Use `fake_aws.respond("iam list-open-id-connect-providers", json_str)` to register
    a response. Subcommand match is exact (first two argv tokens). Anything unmatched
    returns empty stdout and exit 0.

    Inspect calls via `fake_aws.calls` — a list of arg lists in invocation order.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "aws_calls.tsv"
    log_file.write_text("")
    responses_dir = tmp_path / "aws_responses"
    responses_dir.mkdir()

    aws_stub = bin_dir / "aws"
    aws_stub.write_text(
        f"""#!/usr/bin/env bash
set -e
# Record argv (TAB-separated, one line per call)
printf '%s\\n' "$(printf '%s\\t' "$@")" >> "{log_file}"

key="$1__$2"
resp_file="{responses_dir}/$key"
if [[ -f "$resp_file.exit" ]]; then
  exit_code=$(cat "$resp_file.exit")
else
  exit_code=0
fi
if [[ -f "$resp_file.out" ]]; then
  cat "$resp_file.out"
fi
exit "$exit_code"
"""
    )
    aws_stub.chmod(0o755)

    # Ensure jq is on PATH (real binary). Don't shadow it.
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    if shutil.which("jq") is None:
        pytest.skip("jq not installed (apt install jq)")

    class FakeAws:
        def respond(self, subcommand: str, stdout: str = "", exit_code: int = 0):
            key = subcommand.replace(" ", "__", 1)
            (responses_dir / f"{key}.out").write_text(stdout)
            (responses_dir / f"{key}.exit").write_text(str(exit_code))

        @property
        def calls(self) -> list[list[str]]:
            text = log_file.read_text()
            return [line.rstrip("\t").split("\t") for line in text.splitlines() if line]

    return FakeAws()
```

- [ ] **Step 2: Add failing tests for preflight**

Append to `tests/test_setup_aws.py`:

```python
VALID_ARGS = [
    "--repo", "owner/name",
    "--region", "us-east-1",
    "--bucket", "my-dora-bucket",
]


def test_preflight_aws_cli_missing(tmp_path, monkeypatch):
    """If `aws` is not on PATH, the script aborts with a clear message."""
    # Empty PATH (still need /bin for shell builtins via env)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    # Move aws out of the way for this test by pointing PATH at a known-empty dir.
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    result = subprocess.run(
        ["bash", str(SCRIPT), *VALID_ARGS],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "aws" in result.stderr.lower()


def test_preflight_caller_identity_failure(fake_aws):
    """If `aws sts get-caller-identity` exits non-zero, the script aborts."""
    fake_aws.respond("sts get-caller-identity", "", exit_code=255)
    result = subprocess.run(
        ["bash", str(SCRIPT), *VALID_ARGS],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "credentials" in result.stderr.lower()


def test_preflight_succeeds_records_account_id(fake_aws):
    """Successful preflight calls sts get-caller-identity exactly once."""
    fake_aws.respond("sts get-caller-identity", '{"Account": "123456789012"}')
    # Stub everything else as no-op so the script can progress past preflight.
    fake_aws.respond("iam list-open-id-connect-providers", '{"OpenIDConnectProviderList": []}')
    fake_aws.respond("iam create-open-id-connect-provider", '{}')
    fake_aws.respond("s3api head-bucket", "", exit_code=0)
    fake_aws.respond("s3api put-public-access-block", "")
    fake_aws.respond("s3api put-bucket-cors", "")
    fake_aws.respond("s3api put-bucket-policy", "")
    fake_aws.respond("iam get-role", "", exit_code=255)  # role absent path
    fake_aws.respond("iam create-role", "")
    fake_aws.respond("iam put-role-policy", "")
    result = subprocess.run(
        ["bash", str(SCRIPT), *VALID_ARGS],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    sts_calls = [c for c in fake_aws.calls if c[:2] == ["sts", "get-caller-identity"]]
    assert len(sts_calls) == 1
```

- [ ] **Step 3: Run tests — expect all FAIL**

Run: `uv run pytest tests/test_setup_aws.py -v -k preflight`
Expected: 3 failures (preflight not implemented).

- [ ] **Step 4: Add preflight block to script**

Append after the validation block in `examples/setup-aws.sh`. Note: the script parses JSON with `jq` rather than relying on `--query/--output text`, so the `aws` stub used in tests (which ignores those flags) still works.

```bash
# --- Preflight -------------------------------------------------------------

command -v aws >/dev/null 2>&1 || die "aws CLI not on PATH (install AWS CLI v2)"
command -v jq  >/dev/null 2>&1 || die "jq not on PATH (apt install jq / brew install jq)"

if ! sts_json="$(aws sts get-caller-identity 2>/dev/null)"; then
  die "aws credentials not configured (run 'aws configure' or set AWS_PROFILE)"
fi
account_id="$(echo "$sts_json" | jq -r '.Account')"
[[ -n "$account_id" && "$account_id" != "null" ]] || die "aws sts get-caller-identity returned no account id"
```

- [ ] **Step 5: Run tests — expect all PASS**

Run: `uv run pytest tests/test_setup_aws.py -v -k preflight`
Expected: 3 passes.

- [ ] **Step 6: Commit**

```bash
git add examples/setup-aws.sh tests/test_setup_aws.py tests/conftest.py
git commit -m "feat(setup-aws): preflight checks for aws/jq/credentials"
```

---

## Task 4: OIDC provider step (idempotent)

**Files:**
- Modify: `examples/setup-aws.sh`
- Modify: `tests/test_setup_aws.py`

- [ ] **Step 1: Add failing tests for OIDC provider**

Append to `tests/test_setup_aws.py`:

```python
def _stub_happy_path(fake_aws, *, oidc_present=False, role_present=False, bucket_status=404):
    """Set up canned responses for everything except the resource-under-test."""
    fake_aws.respond("sts get-caller-identity", '{"Account": "123456789012"}')
    if oidc_present:
        fake_aws.respond(
            "iam list-open-id-connect-providers",
            '{"OpenIDConnectProviderList": [{"Arn": "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"}]}',
        )
    else:
        fake_aws.respond("iam list-open-id-connect-providers", '{"OpenIDConnectProviderList": []}')
    fake_aws.respond("iam create-open-id-connect-provider", "")
    fake_aws.respond("s3api head-bucket", "", exit_code=(0 if bucket_status == 200 else 255))
    fake_aws.respond("s3api create-bucket", "")
    fake_aws.respond("s3api put-public-access-block", "")
    fake_aws.respond("s3api put-bucket-cors", "")
    fake_aws.respond("s3api put-bucket-policy", "")
    if role_present:
        fake_aws.respond("iam get-role", '{"Role": {"Arn": "arn:aws:iam::123456789012:role/dora-report-uploader"}}')
    else:
        fake_aws.respond("iam get-role", "", exit_code=255)
    fake_aws.respond("iam create-role", "")
    fake_aws.respond("iam update-assume-role-policy", "")
    fake_aws.respond("iam put-role-policy", "")


def test_oidc_provider_created_when_absent(fake_aws):
    _stub_happy_path(fake_aws, oidc_present=False)
    result = subprocess.run(
        ["bash", str(SCRIPT), *VALID_ARGS],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    creates = [c for c in fake_aws.calls if c[:2] == ["iam", "create-open-id-connect-provider"]]
    assert len(creates) == 1
    # URL and audience are correct
    create_argv = creates[0]
    assert "https://token.actions.githubusercontent.com" in create_argv
    assert "sts.amazonaws.com" in create_argv


def test_oidc_provider_skipped_when_present(fake_aws):
    _stub_happy_path(fake_aws, oidc_present=True)
    result = subprocess.run(
        ["bash", str(SCRIPT), *VALID_ARGS],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    creates = [c for c in fake_aws.calls if c[:2] == ["iam", "create-open-id-connect-provider"]]
    assert len(creates) == 0
    assert "OIDC provider already exists" in result.stderr or "reusing" in result.stderr
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/test_setup_aws.py -v -k oidc`
Expected: 2 failures (OIDC step not implemented).

- [ ] **Step 3: Add OIDC step**

Append to `examples/setup-aws.sh`:

```bash
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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_setup_aws.py -v -k oidc`
Expected: 2 passes.

- [ ] **Step 5: Commit**

```bash
git add examples/setup-aws.sh tests/test_setup_aws.py
git commit -m "feat(setup-aws): create or reuse IAM OIDC provider"
```

---

## Task 5: S3 bucket step (region-aware, idempotent, BPA tweaks)

**Files:**
- Modify: `examples/setup-aws.sh`
- Modify: `tests/test_setup_aws.py`

- [ ] **Step 1: Add failing tests for bucket creation**

Append to `tests/test_setup_aws.py`:

```python
def test_bucket_created_when_absent_us_east_1(fake_aws):
    _stub_happy_path(fake_aws, bucket_status=404)
    result = subprocess.run(
        ["bash", str(SCRIPT), *VALID_ARGS],  # region = us-east-1
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    creates = [c for c in fake_aws.calls if c[:2] == ["s3api", "create-bucket"]]
    assert len(creates) == 1
    argv = " ".join(creates[0])
    # us-east-1 omits LocationConstraint
    assert "LocationConstraint" not in argv
    assert "my-dora-bucket" in argv


def test_bucket_created_when_absent_other_region(fake_aws):
    _stub_happy_path(fake_aws, bucket_status=404)
    args = [
        "--repo", "owner/name",
        "--region", "eu-west-1",
        "--bucket", "my-dora-bucket",
    ]
    result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    creates = [c for c in fake_aws.calls if c[:2] == ["s3api", "create-bucket"]]
    assert len(creates) == 1
    argv = " ".join(creates[0])
    assert "LocationConstraint" in argv
    assert "eu-west-1" in argv


def test_bucket_skipped_when_present(fake_aws):
    _stub_happy_path(fake_aws, bucket_status=200)
    result = subprocess.run(["bash", str(SCRIPT), *VALID_ARGS], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    creates = [c for c in fake_aws.calls if c[:2] == ["s3api", "create-bucket"]]
    assert len(creates) == 0


def test_bucket_skipped_with_existing_bucket_flag(fake_aws):
    _stub_happy_path(fake_aws)
    args = [
        "--repo", "owner/name",
        "--region", "us-east-1",
        "--existing-bucket", "shared-ci",
    ]
    result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    head_calls = [c for c in fake_aws.calls if c[:2] == ["s3api", "head-bucket"]]
    create_calls = [c for c in fake_aws.calls if c[:2] == ["s3api", "create-bucket"]]
    bpa_calls = [c for c in fake_aws.calls if c[:2] == ["s3api", "put-public-access-block"]]
    assert head_calls == []
    assert create_calls == []
    assert bpa_calls == []


```

Note: the script does not unit-test the "bucket name taken by another AWS account" (403) path — disambiguating 403 from 404 in bash via `head-bucket` alone is awkward, and `create-bucket` will surface the AWS error verbatim if the script falls through. The 403 path is exercised in Task 12's manual smoke test.

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/test_setup_aws.py -v -k bucket`
Expected: 4 failures.

- [ ] **Step 3: Add bucket step**

Append to `examples/setup-aws.sh`:

```bash
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
fi
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_setup_aws.py -v -k bucket`
Expected: 4 passes.

- [ ] **Step 5: Commit**

```bash
git add examples/setup-aws.sh tests/test_setup_aws.py
git commit -m "feat(setup-aws): create bucket idempotently with region-aware syntax + BPA"
```

---

## Task 6: Bucket CORS

**Files:**
- Modify: `examples/setup-aws.sh`
- Modify: `tests/test_setup_aws.py`

- [ ] **Step 1: Add failing test**

```python
def test_bucket_cors_applied(fake_aws):
    _stub_happy_path(fake_aws, bucket_status=200)
    result = subprocess.run(["bash", str(SCRIPT), *VALID_ARGS], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    cors_calls = [c for c in fake_aws.calls if c[:2] == ["s3api", "put-bucket-cors"]]
    assert len(cors_calls) == 1
    argv = " ".join(cors_calls[0])
    assert "my-dora-bucket" in argv
    # Spot-check: the CORS JSON includes "GET" and "*"
    assert "GET" in argv
    assert "*" in argv


def test_bucket_cors_skipped_with_existing_bucket(fake_aws):
    _stub_happy_path(fake_aws)
    args = ["--repo", "o/n", "--region", "us-east-1", "--existing-bucket", "shared"]
    result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    cors_calls = [c for c in fake_aws.calls if c[:2] == ["s3api", "put-bucket-cors"]]
    assert cors_calls == []
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/test_setup_aws.py -v -k cors`
Expected: 2 failures.

- [ ] **Step 3: Add CORS step**

Append to the `else` branch of the bucket block (i.e. only when we own the bucket, not when `--existing-bucket`):

```bash
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
```

(Place this inside the `else` block from Task 5, after the `put-public-access-block` call. Closing `fi` of that `if` stays at the same place.)

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_setup_aws.py -v -k cors`
Expected: 2 passes.

- [ ] **Step 5: Commit**

```bash
git add examples/setup-aws.sh tests/test_setup_aws.py
git commit -m "feat(setup-aws): apply CORS config (GET from any origin)"
```

---

## Task 7: Bucket public-read policy on `dora-report.json`

**Files:**
- Modify: `examples/setup-aws.sh`
- Modify: `tests/test_setup_aws.py`

- [ ] **Step 1: Add failing test**

```python
def test_bucket_public_policy_applied(fake_aws):
    _stub_happy_path(fake_aws, bucket_status=200)
    result = subprocess.run(["bash", str(SCRIPT), *VALID_ARGS], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    policy_calls = [c for c in fake_aws.calls if c[:2] == ["s3api", "put-bucket-policy"]]
    assert len(policy_calls) == 1
    # The policy ARN must scope to dora-report.json only — never the whole bucket.
    argv = " ".join(policy_calls[0])
    assert "arn:aws:s3:::my-dora-bucket/dora-report.json" in argv
    assert "arn:aws:s3:::my-dora-bucket/*" not in argv
    assert "arn:aws:s3:::my-dora-bucket/dora.db" not in argv
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/test_setup_aws.py -v -k public_policy`
Expected: 1 failure.

- [ ] **Step 3: Add bucket-policy step**

Append to the same `else` block (after CORS):

```bash
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
```

- [ ] **Step 4: Run test — expect PASS**

Run: `uv run pytest tests/test_setup_aws.py -v -k public_policy`
Expected: 1 pass.

- [ ] **Step 5: Commit**

```bash
git add examples/setup-aws.sh tests/test_setup_aws.py
git commit -m "feat(setup-aws): bucket policy granting public read on dora-report.json only"
```

---

## Task 8: IAM role + trust policy (create or update path)

**Files:**
- Modify: `examples/setup-aws.sh`
- Modify: `tests/test_setup_aws.py`

- [ ] **Step 1: Add failing tests**

```python
def test_role_created_when_absent_no_branch(fake_aws):
    _stub_happy_path(fake_aws, role_present=False)
    result = subprocess.run(["bash", str(SCRIPT), *VALID_ARGS], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    create_calls = [c for c in fake_aws.calls if c[:2] == ["iam", "create-role"]]
    update_calls = [c for c in fake_aws.calls if c[:2] == ["iam", "update-assume-role-policy"]]
    assert len(create_calls) == 1
    assert len(update_calls) == 0
    argv = " ".join(create_calls[0])
    # No --branch given → sub matches any ref
    assert "repo:owner/name:*" in argv
    # OIDC provider ARN is referenced
    assert "oidc-provider/token.actions.githubusercontent.com" in argv
    # Account id from preflight is interpolated
    assert "123456789012" in argv


def test_role_created_with_branch_restriction(fake_aws):
    _stub_happy_path(fake_aws, role_present=False)
    args = [*VALID_ARGS, "--branch", "main"]
    result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    create_calls = [c for c in fake_aws.calls if c[:2] == ["iam", "create-role"]]
    argv = " ".join(create_calls[0])
    assert "repo:owner/name:ref:refs/heads/main" in argv


def test_role_updates_trust_policy_when_present(fake_aws):
    _stub_happy_path(fake_aws, role_present=True)
    result = subprocess.run(["bash", str(SCRIPT), *VALID_ARGS], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    create_calls = [c for c in fake_aws.calls if c[:2] == ["iam", "create-role"]]
    update_calls = [c for c in fake_aws.calls if c[:2] == ["iam", "update-assume-role-policy"]]
    assert len(create_calls) == 0
    assert len(update_calls) == 1
    assert "updating existing role" in result.stderr.lower()


def test_no_branch_emits_recommendation(fake_aws):
    _stub_happy_path(fake_aws, role_present=False)
    result = subprocess.run(["bash", str(SCRIPT), *VALID_ARGS], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--branch main" in result.stderr  # recommendation note
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/test_setup_aws.py -v -k role`
Expected: 4 failures.

- [ ] **Step 3: Add role + trust-policy step**

Append to `examples/setup-aws.sh`:

```bash
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
  echo "→ role exists; updating existing role's trust policy" >&2
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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_setup_aws.py -v -k role`
Expected: 4 passes.

- [ ] **Step 5: Commit**

```bash
git add examples/setup-aws.sh tests/test_setup_aws.py
git commit -m "feat(setup-aws): create or refresh IAM role with OIDC trust policy"
```

---

## Task 9: Inline IAM policy

**Files:**
- Modify: `examples/setup-aws.sh`
- Modify: `tests/test_setup_aws.py`

- [ ] **Step 1: Add failing test**

```python
def test_inline_policy_grants_only_two_keys(fake_aws):
    _stub_happy_path(fake_aws, role_present=True)
    result = subprocess.run(["bash", str(SCRIPT), *VALID_ARGS], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    pol_calls = [c for c in fake_aws.calls if c[:2] == ["iam", "put-role-policy"]]
    assert len(pol_calls) == 1
    argv = " ".join(pol_calls[0])
    assert "arn:aws:s3:::my-dora-bucket/dora.db" in argv
    assert "arn:aws:s3:::my-dora-bucket/dora-report.json" in argv
    assert "arn:aws:s3:::my-dora-bucket/*" not in argv
    assert "s3:GetObject" in argv
    assert "s3:PutObject" in argv
    # Spec drops PutObjectAcl (bucket policy supersedes ACLs).
    assert "s3:PutObjectAcl" not in argv


def test_inline_policy_uses_existing_bucket_name(fake_aws):
    _stub_happy_path(fake_aws, role_present=True)
    args = ["--repo", "o/n", "--region", "us-east-1", "--existing-bucket", "shared-ci"]
    result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    pol_calls = [c for c in fake_aws.calls if c[:2] == ["iam", "put-role-policy"]]
    argv = " ".join(pol_calls[0])
    assert "arn:aws:s3:::shared-ci/dora.db" in argv
    assert "arn:aws:s3:::shared-ci/dora-report.json" in argv
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/test_setup_aws.py -v -k inline_policy`
Expected: 2 failures.

- [ ] **Step 3: Add inline-policy step**

Append to `examples/setup-aws.sh`:

```bash
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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_setup_aws.py -v -k inline_policy`
Expected: 2 passes.

- [ ] **Step 5: Commit**

```bash
git add examples/setup-aws.sh tests/test_setup_aws.py
git commit -m "feat(setup-aws): inline IAM policy scoped to two S3 keys"
```

---

## Task 10: Final summary block on stdout

**Files:**
- Modify: `examples/setup-aws.sh`
- Modify: `tests/test_setup_aws.py`

- [ ] **Step 1: Add failing tests**

```python
def test_summary_block_owned_bucket(fake_aws):
    _stub_happy_path(fake_aws, role_present=True, bucket_status=200)
    result = subprocess.run(["bash", str(SCRIPT), *VALID_ARGS], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "AWS setup complete." in out
    assert "Bucket:   my-dora-bucket (us-east-1)" in out
    assert "Role ARN: arn:aws:iam::123456789012:role/dora-report-uploader" in out
    assert "role-to-assume: arn:aws:iam::123456789012:role/dora-report-uploader" in out
    assert "aws-region:     us-east-1" in out
    assert "bucket:         my-dora-bucket" in out
    assert "https://dimagi.github.io/dora/?url=https://my-dora-bucket.s3.us-east-1.amazonaws.com/dora-report.json" in out


def test_summary_block_existing_bucket_includes_caveat(fake_aws):
    _stub_happy_path(fake_aws, role_present=True)
    args = ["--repo", "o/n", "--region", "us-east-1", "--existing-bucket", "shared-ci"]
    result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "shared-ci" in out
    # Note about CORS / public-policy on the user's responsibility
    assert "CORS" in out and "policy" in out
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/test_setup_aws.py -v -k summary`
Expected: 2 failures.

- [ ] **Step 3: Add summary block**

Append to `examples/setup-aws.sh`:

```bash
# --- Summary ---------------------------------------------------------------

dashboard_url="https://dimagi.github.io/dora/?url=https://${bucket_name}.s3.${region}.amazonaws.com/dora-report.json"

cat <<EOF
─────────────────────────────────────────────────
AWS setup complete.

Bucket:   ${bucket_name} (${region})
Role ARN: ${role_arn}

In your dora-report.yml workflow, set:
  role-to-assume: ${role_arn}
  aws-region:     ${region}
  bucket:         ${bucket_name}

Public dashboard URL once the workflow runs:
  ${dashboard_url}
EOF

if [[ -n "$existing_bucket" ]]; then
  cat <<EOF

Note: --existing-bucket was used. Bucket CORS and public-read policy
on '${bucket_name}' are your responsibility — see README "S3 variant"
for the JSON snippets.
EOF
fi

echo "─────────────────────────────────────────────────"
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_setup_aws.py -v -k summary`
Expected: 2 passes.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/test_setup_aws.py -v`
Expected: all tests pass (~20 tests).

- [ ] **Step 6: Commit**

```bash
git add examples/setup-aws.sh tests/test_setup_aws.py
git commit -m "feat(setup-aws): print paste-ready summary block on stdout"
```

---

## Task 11: Update example workflow + README

**Files:**
- Modify: `examples/workflows/dora-report.yml`
- Modify: `README.md`

- [ ] **Step 1: Update `examples/workflows/dora-report.yml`**

In the S3-variant comment block (currently starts at line 61, `# --- S3 variant (OIDC, recommended) ---`), make two edits:

  1. Replace the "AWS one-time setup:" paragraph (currently lines 66–89) with a pointer to the script. Keep the JSON shapes as a comment-out reference for hand-rollers, but flag them as reference-only.

  2. In the `Upload to S3` step inside the comment block (currently lines 110–115), drop `--public-read` from the `dora upload` line.

The new top of the S3-variant block becomes:

```yaml
# --- S3 variant (OIDC, recommended) -----------------------------------------
# AWS one-time setup: run examples/setup-aws.sh — see README "S3 variant"
# for details. The script provisions: IAM OIDC provider, S3 bucket (+ CORS
# and a public-read bucket policy on dora-report.json), and an IAM role
# scoped to your repo.
#
# Reference only — examples/setup-aws.sh does this for you:
#
#   1. IAM → Identity providers → Add provider:
#        Type: OpenID Connect
#        URL:  https://token.actions.githubusercontent.com
#        Audience: sts.amazonaws.com
#   2. Create an IAM role (e.g. `dora-report-uploader`) with a trust policy
#      restricting it to your repo (and optionally branch):
#        ... (trust policy JSON unchanged) ...
#   3. Attach a policy granting GetObject + PutObject on dora.db and
#      dora-report.json under your bucket.
```

(The full trust-policy JSON block stays as-is — it's reference for hand-rollers.)

The `Upload to S3` reference step becomes:

```yaml
#       - name: Upload to S3
#         run: |
#           uv tool install "git+https://github.com/dimagi/dora[s3]"
#           dora upload dora-report.json \
#             --target s3://my-bucket/dora-report.json
#           aws s3 cp dora.db s3://my-bucket/dora.db   # keep DB private
```

(The `--public-read` flag is removed; the bucket policy now makes
`dora-report.json` publicly readable.)

- [ ] **Step 2: Update `README.md` § S3 variant**

In `README.md`, find the section starting at line 80 (`### S3 variant`). Replace the paragraph beginning "**Recommended auth: GitHub OIDC.** Short-lived credentials assumed at workflow runtime…" through the end of the OIDC paragraph (currently ends "See the example workflow comments for the exact policy/role shape." — line 89) with:

```markdown
**Recommended auth: GitHub OIDC.** Short-lived credentials assumed at workflow runtime; no long-lived AWS keys to rotate, no secrets stored in the repo. Run [`examples/setup-aws.sh`](examples/setup-aws.sh) to provision the bucket, OIDC provider, and IAM role in one command:

    ./examples/setup-aws.sh \
      --repo OWNER/REPO --bucket BUCKET --region REGION [--branch main]

The script prints the role ARN and bucket details to paste into your workflow. See `examples/setup-aws.sh --help` for full options, or the workflow file's S3-variant section for the underlying resources if you'd rather provision by hand.
```

The "Fallback: long-lived access keys" paragraph and the "Either way, you'll also need" list stay unchanged. The "Bucket CORS config" and "DB is stored privately; only the JSON is `--public-read`" bullets stay too — but update the second bullet to:

```markdown
- The DB is stored privately; only the JSON is publicly readable (via a bucket policy scoped to `dora-report.json`)
```

- [ ] **Step 3: Sanity-check the workflow file is still valid YAML**

Run: `python -c "import yaml; yaml.safe_load(open('examples/workflows/dora-report.yml'))"`
Expected: no exception (the entire S3 variant lives in `#` comments, so YAML stays parseable regardless).

- [ ] **Step 4: Commit**

```bash
git add examples/workflows/dora-report.yml README.md
git commit -m "docs: point S3-variant adopters at examples/setup-aws.sh"
```

---

## Task 12: Lint + manual smoke-test checklist

**Files:**
- Modify: `examples/setup-aws.sh` (only if shellcheck flags issues)
- Create: `docs/superpowers/plans/2026-04-27-aws-setup-script-smoke-test.md` (persistable smoke-test checklist for adopters and future regressions)

- [ ] **Step 1: Run `shellcheck`**

Run: `shellcheck examples/setup-aws.sh`
Expected: no warnings or errors.

If shellcheck flags anything, fix in place. Common issues to expect: SC2086 (unquoted vars), SC2155 (declare-and-assign masks return values). The standard fix is `local var; var="$(cmd)"` for the latter, and `"$var"` quoting for the former. The script does not use `local` (no functions yet beyond `usage`/`die`); SC2155 will only apply if those grow.

- [ ] **Step 2: Write smoke-test checklist**

Create `docs/superpowers/plans/2026-04-27-aws-setup-script-smoke-test.md`:

```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-04-27-aws-setup-script-smoke-test.md
git commit -m "docs: add manual smoke-test checklist for setup-aws.sh"
```

---

## Self-review

After implementing all tasks, run the full test suite and confirm clean state:

```bash
uv run pytest tests/test_setup_aws.py -v
shellcheck examples/setup-aws.sh
git status   # should be clean
git log --oneline | head -15
```

Then walk the smoke-test checklist (Task 12, Step 2) against a real AWS test account before opening the PR.
