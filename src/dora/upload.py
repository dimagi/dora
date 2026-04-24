"""Upload a file to a supported target URL.

Currently supports `s3://bucket/key`. Credentials come from the default
boto3 chain (env vars, `~/.aws/credentials`, IAM role) — no
dora-specific flags.

`boto3` is an optional extra: install with `uv tool install "dora-metrics[s3]"`
or `pip install dora-metrics[s3]`.
"""

from pathlib import Path

try:
    import boto3
except ImportError as exc:
    boto3 = None  # type: ignore[assignment]
    _boto_import_error = exc
else:
    _boto_import_error = None


def parse_s3_target(target: str) -> tuple[str, str]:
    """Parse `s3://bucket/key...` → (bucket, key). Raises ValueError on bad input."""
    if not target.startswith("s3://"):
        raise ValueError(f"Target must start with s3://, got: {target!r}")
    rest = target[len("s3://"):]
    if "/" not in rest:
        raise ValueError(
            f"Target must include bucket and key (s3://bucket/key), got: {target!r}"
        )
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError(
            f"Target must include bucket and key (s3://bucket/key), got: {target!r}"
        )
    return bucket, key


def upload_s3(
    path: str,
    target: str,
    *,
    content_type: str,
    public_read: bool,
) -> None:
    """Upload `path` to an S3 `target` URL."""
    if boto3 is None:
        raise RuntimeError(
            "boto3 not installed. Install the s3 extra: "
            "`uv tool install \"dora-metrics[s3]\"`"
        ) from _boto_import_error

    bucket, key = parse_s3_target(target)
    data = Path(path).read_bytes()
    client = boto3.client("s3")
    kwargs: dict = {
        "Bucket":      bucket,
        "Key":         key,
        "Body":        data,
        "ContentType": content_type,
    }
    if public_read:
        kwargs["ACL"] = "public-read"
    client.put_object(**kwargs)
