"""Make rendered media reachable by a public URL.

Instagram downloads media from a URL you give it, so every image or video has
to be publicly reachable for a few minutes while the container is created.

Backends (MEDIA_BACKEND):
  s3      - any S3-compatible bucket with public read, e.g. Cloudflare R2
            (free tier covers this project). Needs S3_* variables.
  github  - commit files into the repo and use raw.githubusercontent.com.
            Only works when the repository is public.
"""

from __future__ import annotations

import mimetypes
import subprocess
import time
from pathlib import Path

import requests

from .config import ROOT, env


def upload(paths: list[Path], prefix: str) -> list[str]:
    backend = env("MEDIA_BACKEND", "s3")
    if backend == "s3":
        return _upload_s3(paths, prefix)
    if backend == "github":
        return _upload_github(paths)
    raise SystemExit(f"Neznámý MEDIA_BACKEND '{backend}'")


def _upload_s3(paths: list[Path], prefix: str) -> list[str]:
    import boto3  # optional dependency, only needed for this backend

    bucket = env("S3_BUCKET", required=True)
    public_base = env("S3_PUBLIC_BASE_URL", required=True).rstrip("/")
    client = boto3.client(
        "s3",
        endpoint_url=env("S3_ENDPOINT_URL"),
        aws_access_key_id=env("S3_ACCESS_KEY_ID", required=True),
        aws_secret_access_key=env("S3_SECRET_ACCESS_KEY", required=True),
        region_name=env("S3_REGION", "auto"),
    )
    urls = []
    for path in paths:
        key = f"{prefix}/{path.name}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        client.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": content_type})
        urls.append(f"{public_base}/{key}")
    _wait_public(urls)
    return urls


def _upload_github(paths: list[Path]) -> list[str]:
    repo = env("GITHUB_REPOSITORY", required=True)
    branch = env("MEDIA_BRANCH", "main")
    rel = [str(p.relative_to(ROOT)) for p in paths]
    subprocess.run(["git", "add", "-f", *rel], cwd=ROOT, check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if staged.returncode:
        subprocess.run(["git", "commit", "-m", "media: upload rendered files"], cwd=ROOT, check=True)
        subprocess.run(["git", "push", "origin", f"HEAD:{branch}"], cwd=ROOT, check=True)
    urls = [f"https://raw.githubusercontent.com/{repo}/{branch}/{r}" for r in rel]
    _wait_public(urls)
    return urls


def _wait_public(urls: list[str], timeout: int = 120) -> None:
    deadline = time.time() + timeout
    for url in urls:
        while True:
            try:
                if requests.head(url, timeout=15, allow_redirects=True).status_code == 200:
                    break
            except requests.RequestException:
                pass
            if time.time() > deadline:
                raise RuntimeError(f"Soubor není veřejně dostupný: {url}")
            time.sleep(5)
