"""Tests for src/dora/upload.py — S3 target parsing + boto3 call shape."""

from unittest.mock import MagicMock, patch

import pytest

from dora import upload


def test_parse_s3_target_extracts_bucket_and_key():
    bucket, key = upload.parse_s3_target("s3://my-bucket/path/to/report.json")
    assert bucket == "my-bucket"
    assert key    == "path/to/report.json"


def test_parse_s3_target_rejects_non_s3_url():
    with pytest.raises(ValueError, match="must start with s3://"):
        upload.parse_s3_target("https://example.com/a.json")


def test_parse_s3_target_rejects_missing_key():
    with pytest.raises(ValueError, match="bucket and key"):
        upload.parse_s3_target("s3://just-a-bucket")


def test_upload_s3_calls_boto3_put_object(tmp_path):
    f = tmp_path / "report.json"
    f.write_text('{"hello": "world"}')
    mock_client = MagicMock()
    with patch("dora.upload.boto3.client", return_value=mock_client):
        upload.upload_s3(str(f), "s3://bk/report.json",
                         content_type="application/json", public_read=False)
    assert mock_client.put_object.called
    kwargs = mock_client.put_object.call_args.kwargs
    assert kwargs["Bucket"]      == "bk"
    assert kwargs["Key"]         == "report.json"
    assert kwargs["ContentType"] == "application/json"
    assert "ACL" not in kwargs   # public_read=False


def test_upload_s3_sets_public_read_acl(tmp_path):
    f = tmp_path / "r.json"
    f.write_text("{}")
    mock_client = MagicMock()
    with patch("dora.upload.boto3.client", return_value=mock_client):
        upload.upload_s3(str(f), "s3://bk/r.json",
                         content_type="application/json", public_read=True)
    assert mock_client.put_object.call_args.kwargs["ACL"] == "public-read"
