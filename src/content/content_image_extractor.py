import base64
import logging
import os
from typing import Optional

import httpx
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def load_prompt(prompt_file: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompts_dir = os.path.join(os.path.dirname(__file__), "..", "prompts")
    with open(os.path.join(prompts_dir, prompt_file), "r") as f:
        return f.read()


IMAGE_DESCRIPTION_PROMPT = load_prompt("image-description.md")


class ContentImageExtractor:
    """Extracts descriptive content from images using a vision model.

    Supports images from local file paths or internet URLs.
    """

    def __init__(
        self,
        openai_endpoint: Optional[str] = None,
        vision_model: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        self.openai_endpoint = openai_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.vision_model = vision_model or os.getenv("AZURE_OPENAI_VISION_DEPLOYMENT_NAME", "gpt-4o")
        self.api_version = api_version or os.getenv("OPENAI_API_VERSION", "2024-10-21")

        self._client = None

        logger.info(
            f"ContentImageExtractor initialized: endpoint='{self.openai_endpoint}', "
            f"vision_model='{self.vision_model}'"
        )

    def _get_client(self) -> AzureOpenAI:
        """Create or return the Azure OpenAI client."""
        if self._client:
            return self._client

        api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
        if api_key:
            logger.info("Azure OpenAI vision auth mode: API key")
            self._client = AzureOpenAI(
                azure_deployment=self.vision_model,
                api_version=self.api_version,
                azure_endpoint=self.openai_endpoint,
                api_key=api_key,
            )
        else:
            logger.info("Azure OpenAI vision auth mode: Entra ID (DefaultAzureCredential)")
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            self._client = AzureOpenAI(
                azure_deployment=self.vision_model,
                api_version=self.api_version,
                azure_endpoint=self.openai_endpoint,
                azure_ad_token_provider=token_provider,
            )

        return self._client

    def _load_image_as_data_url(self, file_path: str) -> str:
        """Load a local image file and return it as a base64 data URL."""
        ext = os.path.splitext(file_path)[1].lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
        }
        mime_type = mime_types.get(ext, "image/png")

        with open(file_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        return f"data:{mime_type};base64,{image_data}"

    def _fetch_image_as_data_url(self, url: str) -> str:
        """Fetch an image from a URL and return it as a base64 data URL."""
        logger.info(f"Fetching image from: {url}")
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()

        content_type = response.headers.get("content-type", "image/png").split(";")[0]
        image_data = base64.b64encode(response.content).decode("utf-8")
        return f"data:{content_type};base64,{image_data}"

    def describe_image(
        self,
        source: str,
        prompt: Optional[str] = None,
    ) -> str:
        """Describe an image from a local file path or internet URL.

        Args:
            source: A local file path or an HTTP(S) URL pointing to an image.
            prompt: Optional context prompt to prepend to the default image description prompt.
                    If provided, it is combined with the default prompt for richer context.

        Returns:
            A text description of the image content.
        """
        if prompt is None:
            full_prompt = IMAGE_DESCRIPTION_PROMPT
        else:
            full_prompt = prompt + "\n\n" + IMAGE_DESCRIPTION_PROMPT

        # Determine if source is a URL or local path
        if source.startswith(("http://", "https://")):
            image_content = {"type": "image_url", "image_url": {"url": source}}
        else:
            if not os.path.isfile(source):
                raise FileNotFoundError(f"Image file not found: {source}")
            data_url = self._load_image_as_data_url(source)
            image_content = {"type": "image_url", "image_url": {"url": data_url}}

        client = self._get_client()
        logger.info(f"Describing image from: {source}")

        response = client.chat.completions.create(
            model=self.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": full_prompt},
                        image_content,
                    ],
                }
            ],
        )

        description = response.choices[0].message.content.strip()
        logger.debug(f"Generated description ({len(description)} chars) for: {source}")
        return description
