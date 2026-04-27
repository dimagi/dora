"""Tests for examples/setup-aws.sh."""

import subprocess
from pathlib import Path

import pytest

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


VALID_ARGS = [
    "--repo", "owner/name",
    "--region", "us-east-1",
    "--bucket", "my-dora-bucket",
]


def test_preflight_aws_cli_missing(tmp_path, monkeypatch):
    """If `aws` is not on PATH, the script aborts with a clear message."""
    # Point PATH at a known-empty dir (but keep /bin for bash).
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", f"{empty}:/usr/bin:/bin")
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
