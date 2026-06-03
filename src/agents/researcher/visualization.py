"""Visualization generation tool for the researcher agent."""

import os
from pathlib import Path

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv(override=True)

_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "visualization_generation.md"

_credential = DefaultAzureCredential()


def _get_image_client() -> AzureOpenAI:
    """Create an Azure OpenAI client configured for image generation."""
    token_provider = get_bearer_token_provider(
        _credential, "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.getenv("AZURE_OPENAI_IMAGE_API_VERSION", "2024-10-21"),
        azure_ad_token_provider=token_provider,
    )


def _load_prompt_template() -> str:
    """Load the visualization generation prompt template."""
    return _PROMPT_PATH.read_text(encoding="utf-8")


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
    """Generate a whiteboard-style architecture visualization using the prompt template.

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
    layer_block = "\n".join(layers)
    component_block = "\n".join(components)
    flow_block = "\n".join(flows)
    callout_block = "\n".join(callouts) if callouts else "Key architectural benefit\nBusiness value delivered"

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

    # Determine image size from aspect ratio
    size_map = {
        "16:9": "1792x1024",
        "4:3": "1024x1024",
        "1:1": "1024x1024",
    }
    size = size_map.get(aspect_ratio, "1792x1024")

    # Generate the image
    client = _get_image_client()
    deployment = os.getenv("AZURE_OPENAI_IMAGE_DEPLOYMENT_NAME", "dall-e-3")

    response = client.images.generate(
        model=deployment,
        prompt=prompt,
        size=size,
        quality="hd",
        n=1,
    )

    image_url = response.data[0].url

    # Download and save
    import urllib.request

    if not output_path:
        safe_title = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in title)
        output_path = f"{safe_title}.png"

    urllib.request.urlretrieve(image_url, output_path)

    return f"Visualization saved to: {output_path}"
