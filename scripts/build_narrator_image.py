"""
Remote-build the Shopping Claw OpenClaw container in Azure Container Registry.

Runs the Docker build *inside Azure* with `az acr build` (ACR Tasks) — no local
Docker daemon required. The build context is the narrator agent directory, which
holds the Dockerfile that bakes OpenClaw + the shopping-claw skill into the image.

Usage:
    python scripts/build_narrator_image.py
    python scripts/build_narrator_image.py --tag shopping-claw:v2

Configuration (.env or environment variables):
  AZURE_CONTAINER_REGISTRY_ENDPOINT   ACR login server, e.g. myacr.azurecr.io   (required)
  NARRATOR_IMAGE_TAG                   image:tag to build   (default: shopping-claw:latest)
  OPENCLAW_VERSION                     openclaw npm version baked in   (default: latest)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUILD_CONTEXT = _REPO_ROOT / "src" / "agents" / "narrator"


def main() -> int:
    parser = argparse.ArgumentParser(description="Remote-build the Shopping Claw image in ACR.")
    parser.add_argument(
        "--tag",
        default=os.getenv("NARRATOR_IMAGE_TAG", "shopping-claw:latest"),
        help="image:tag to build (default: shopping-claw:latest)",
    )
    parser.add_argument(
        "--openclaw-version",
        default=os.getenv("OPENCLAW_VERSION", "latest"),
        help="openclaw npm version to bake into the image (default: latest)",
    )
    args = parser.parse_args()

    acr_endpoint = os.getenv("AZURE_CONTAINER_REGISTRY_ENDPOINT", "")
    if not acr_endpoint:
        sys.exit("❌ AZURE_CONTAINER_REGISTRY_ENDPOINT is not set (e.g. 'myacr.azurecr.io').")
    acr_name = acr_endpoint.split(".")[0]

    dockerfile = _BUILD_CONTEXT / "Dockerfile"
    if not dockerfile.is_file():
        sys.exit(f"❌ Dockerfile not found at {dockerfile}")

    print(f"🏗️  Remote-building {acr_endpoint}/{args.tag}")
    print(f"   registry: {acr_name}")
    print(f"   context:  {_BUILD_CONTEXT}")
    print(f"   openclaw: {args.openclaw_version}")
    print("   (this runs in the cloud via ACR Tasks — no local Docker needed)\n")

    cmd = [
        "az", "acr", "build",
        "--registry", acr_name,
        "--image", args.tag,
        "--platform", "linux/amd64",
        "--build-arg", f"OPENCLAW_VERSION={args.openclaw_version}",
        str(_BUILD_CONTEXT),
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return result.returncode

    print(f"\n✅ Built and pushed: {acr_endpoint}/{args.tag}")
    print("   Boot it with: python src/agents/narrator/shopping_claw.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
