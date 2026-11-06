"""S3 Bucket — document loader `s3`."""

import asyncio
import os
from typing import Any, Dict, List

import loaders
from loaders.base import Document, LoaderError, LoaderSpec

LOADER = LoaderSpec(
    type="s3",
    label="S3 Bucket",
    icon="🪣",
    category="Cloud Storage",
    desc="Stream documents from an AWS S3 prefix",
    source_label="S3 URI (s3://bucket/prefix)",
    placeholder="s3://my-bucket/docs/",
    aliases=("s3directory", "s3file", "s3loader", "awss3"),
    order=10,
)


def _list_and_read(bucket: str, prefix: str, cfg: Dict[str, Any]) -> List[Document]:
    import boto3

    conn = cfg.get("connection") or {}
    session = boto3.session.Session(
        aws_access_key_id=conn.get("access_key_id") or os.environ.get("AWS_ACCESS_KEY_ID") or None,
        aws_secret_access_key=conn.get("secret_access_key") or os.environ.get("AWS_SECRET_ACCESS_KEY") or None,
        region_name=conn.get("region") or os.environ.get("AWS_REGION") or None,
    )
    s3 = session.client("s3")
    max_files = int(cfg.get("max_files", 100))
    docs: List[Document] = []
    read = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            parse = loaders.parser_for(key)
            if parse is None or obj.get("Size", 0) > 50 * 1024 * 1024:
                continue
            read += 1
            if read > max_files:
                return docs
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            try:
                for d in parse(f"s3://{bucket}/{key}", body, cfg):
                    docs.append(d)
            except Exception:
                continue
    return docs


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    """Every supported file under an s3://bucket/prefix (credentials from a linked AWS S3 connection or env)."""
    if not source.startswith("s3://"):
        raise LoaderError("Source must look like s3://bucket/prefix")
    bucket, _, prefix = source[len("s3://"):].partition("/")
    try:
        docs = await asyncio.to_thread(_list_and_read, bucket, prefix, cfg)
    except Exception as e:
        raise LoaderError(f"S3 error: {e}")
    if not docs:
        raise LoaderError(f"No readable files under {source}. Supported: {', '.join(loaders.supported_extensions())}")
    return docs
