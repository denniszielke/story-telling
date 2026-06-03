"""Visualization generation tool for the researcher agent.

Uses the Microsoft AI Image generation endpoint (`MAI-Image-2e`) exposed by
Azure AI Foundry at `/mai/v1/images/generations`. Authenticates with Entra ID
via `DefaultAzureCredential` unless `AZURE_OPENAI_API_KEY` is set.
"""

import base64
import os
from pathlib import Path

import httpx
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv

load_dotenv(override=True)

_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "visualization_generation.md"

_credential = DefaultAzureCredential()
_token_provider = get_bearer_token_provider(
    _credential, "https://cognitiveservices.azure.com/.default"
)


def _load_prompt_template() -> str:
    """Load the visualization generation prompt template."""
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _mai_endpoint() -> str:
    """Resolve the MAI-Image services endpoint.

    Priority:
      1. `AZURE_AI_SERVICES_ENDPOINT` (preferred — the `*.services.ai.azure.com` host).
      2. Derive from `AZURE_OPENAI_ENDPOINT` by swapping `.openai.azure.com`
         for `.services.ai.azure.com`.
    """
    base = os.getenv("AZURE_AI_SERVICES_ENDPOINT")
    if not base:
        openai_ep = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        base = openai_ep.replace(".openai.azure.com", ".services.ai.azure.com")
    base = base.rstrip("/")
    return f"{base}/mai/v1/images/generations"


def _auth_headers() -> dict[str, str]:
    """Build auth headers (api-key takes precedence, otherwise Entra bearer)."""
    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_AI_SERVICES_API_KEY")
    if api_key:
        return {"api-key": api_key}
    return {"Authorization": f"Bearer {_token_provider()}"}


def generate_visualization(
    title: str,
    scenario_description: str,
    layers: list[str],
    components: list[str],
    flows: list[str],
    callouts: list[str] | None = None,
    aspect_ratio: str = "16:9",
    output_path: str | None = None,
) -> str:
    """Generate a whiteboard-style architecture visualization using MAI-Image-2e.

    Args:
        title: Title shown at the top of the diagram.
        scenario_description: One-sentence explanation of what the diagram depicts.
        layers: List of layer/section names (typically 3-4) for structural organisation.
        components: List of components to draw as labelled doodles with icons.
        flows: List of key interactions/flows to show with arrows.
        callouts: Optional 2-4 callout notes highlighting business/architectural value.
        aspect_ratio: Aspect ratio for the image (16:9, 4:3, or 1:1).
        output_path: Optional file path to save the generated image. If not provided,
            saves to the current directory with a sanitised title filename.

    Returns:
        A message with the path to the generated image file.
    """
    template = _load_prompt_template()

    # Build the filled prompt
    number_of_layers = len(layers)

    prompt = template
    prompt = prompt.replace("{TITLE}", title)
    prompt = prompt.replace("{SCENARIO_DESCRIPTION}", scenario_description)
    prompt = prompt.replace("{NUMBER_OF_LAYERS}", str(number_of_layers))
    prompt = prompt.replace("{ASPECT_RATIO}", aspect_ratio)

    # Replace layer placeholders
    for i, layer in enumerate(layers, 1):
        prompt = prompt.replace(f"{{LAYER_{i}_NAME}}", layer)
    prompt = prompt.replace("{OPTIONAL_LAYER_4_NAME}", layers[3] if len(layers) > 3 else "")

    # Replace component placeholders with the full block
    for i, comp in enumerate(components, 1):
        prompt = prompt.replace(f"{{COMPONENT_{i}}}", comp)
    # Clean up remaining component placeholders
    for i in range(len(components) + 1, 10):
        prompt = prompt.replace(f"{{COMPONENT_{i}}}", "")
    prompt = prompt.replace("{DATA_STORE_OR_SYSTEM_1}", components[-2] if len(components) >= 2 else "")
    prompt = prompt.replace("{DATA_STORE_OR_SYSTEM_2}", components[-1] if len(components) >= 1 else "")
    prompt = prompt.replace("{OPTIONAL_COMPONENT_CLUSTER}", "")

    # Replace flow placeholders
    for i, flow in enumerate(flows, 1):
        prompt = prompt.replace(f"{{FLOW_{i}}}", flow)
    for i in range(len(flows) + 1, 8):
        prompt = prompt.replace(f"{{FLOW_{i}}}", "")
    prompt = prompt.replace("{OPTIONAL_FLOW_6}", "")
    prompt = prompt.replace("{OPTIONAL_FLOW_7}", "")

    # Replace callout placeholders
    callout_list = callouts or []
    for i, callout in enumerate(callout_list, 1):
        prompt = prompt.replace(f"{{CALLOUT_{i}}}", callout)
    for i in range(len(callout_list) + 1, 5):
        prompt = prompt.replace(f"{{CALLOUT_{i}}}", "")
    prompt = prompt.replace("{OPTIONAL_CALLOUT_4}", "")

    # Determine width/height from aspect ratio (MAI-Image-2e takes explicit dims)
    size_map = {
        "16:9": (1792, 1024),
        "4:3": (1280, 1024),
        "1:1": (1024, 1024),
    }
    width, height = size_map.get(aspect_ratio, (1792, 1024))

    # Call MAI-Image-2e
    payload = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "model": os.getenv("MAI_IMAGE_MODEL", "MAI-Image-2e"),
    }
    headers = {"Content-Type": "application/json", **_auth_headers()}

    with httpx.Client(timeout=120.0) as http:
        response = http.post(_mai_endpoint(), json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

    b64 = result["data"][0]["b64_json"]
    image_bytes = base64.b64decode(b64)

    if not output_path:
        safe_title = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in title)
        output_path = f"{safe_title}.png"

    Path(output_path).write_bytes(image_bytes)

    return f"Visualization saved to: {output_path}"

