"""S3 / object-store reader — built-in tool `s3_reader`."""

import os
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="s3_reader",
    name="S3 / Object Store Reader",
    icon="☁️",
    category="Data & Files",
    description="Lists or reads objects from an AWS S3 bucket. Input is the S3 key (or 'list').",
    default_config={
        "bucket": "",
        "prefix": "",
        "region": "us-east-1",
        "aws_access_key_id": "",
        "aws_secret_access_key": "",
    },
    order=50,
    parameters=params({"key": {"type": "string", "description": "Object key to read, or 'list'"}}),
    input_param="key",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    bucket = cfg.get("bucket", "")
    prefix = cfg.get("prefix", "")
    region = cfg.get("region", "us-east-1")
    aws_key = cfg.get("aws_access_key_id", "") or os.environ.get("AWS_ACCESS_KEY_ID", "")
    aws_secret = cfg.get("aws_secret_access_key", "") or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    key = inp.strip()
    if not bucket:
        return "[S3] 'bucket' is required in config."
    try:
        import boto3
        session_kwargs: Dict[str, Any] = {"region_name": region}
        if aws_key and aws_secret:
            session_kwargs["aws_access_key_id"] = aws_key
            session_kwargs["aws_secret_access_key"] = aws_secret
        s3 = boto3.client("s3", **session_kwargs)
        if not key or key.lower() in ("list", "ls"):
            result = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=50)
            objects = result.get("Contents", [])
            if not objects:
                return f"[S3] No objects found in s3://{bucket}/{prefix}"
            lines = [f"[S3 Listing: s3://{bucket}/{prefix}]"]
            for obj in objects:
                lines.append(f"  {obj['Key']}  ({obj['Size']} bytes)")
            return "\n".join(lines)
        # Read the object
        obj = s3.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read(32768).decode("utf-8", errors="replace")
        return f"[S3: s3://{bucket}/{key}]\n\n{body}"
    except ImportError:
        return "[S3] boto3 is not installed. pip install boto3"
    except Exception as e:
        return f"[S3] Error: {e}"
