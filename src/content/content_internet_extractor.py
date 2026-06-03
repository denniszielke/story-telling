import json
import logging
import os
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup
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


# Map classification types to their extraction prompts
EXTRACTION_PROMPTS = {
    "case-study": load_prompt("case-study-extraction.md"),
    "concept": load_prompt("methodology_pattern_analysis.md")
}


def _match_extraction_prompt(classification: str = "", objective: str = "") -> Optional[str]:
    """Find the best matching extraction prompt for a document.

    Checks the objective field first ("use case" -> case-study prompt,
    "method" -> concept prompt), then falls back to classification matching.
    """
    # Match by objective
    objective_lower = (objective or "").lower()
    if objective_lower == "use case":
        return EXTRACTION_PROMPTS["case-study"]
    if objective_lower == "method":
        return EXTRACTION_PROMPTS["concept"]

    # Fallback: match by classification
    if not classification:
        return None
    classification_lower = classification.lower()
    for key, prompt in EXTRACTION_PROMPTS.items():
        if classification_lower.startswith(key) or key in classification_lower:
            return prompt
    return None


class ContentExtractor:
    """Extracts and enriches content from various sources using LLM and web retrieval.

    Supports different content classification types, each with its own extraction prompt.
    Can fetch web pages, extract structured content via LLM, and generate tags.
    """

    def __init__(
        self,
        openai_endpoint: Optional[str] = None,
        chat_model: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        self.openai_endpoint = openai_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.chat_model = chat_model or os.getenv("AZURE_OPENAI_LARGE_CHAT_DEPLOYMENT_NAME", "gpt-5.4")
        self.api_version = api_version or os.getenv("OPENAI_API_VERSION", "2024-10-21")

        self._chat_client = None

        logger.info(
            f"ContentExtractor initialized: endpoint='{self.openai_endpoint}', "
            f"chat_model='{self.chat_model}'"
        )

    def _get_chat_client(self) -> AzureOpenAI:
        """Create or return the Azure OpenAI chat completion client."""
        if self._chat_client:
            return self._chat_client

        api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
        if api_key:
            logger.info("Azure OpenAI chat auth mode: API key")
            self._chat_client = AzureOpenAI(
                azure_deployment=self.chat_model,
                api_version=self.api_version,
                azure_endpoint=self.openai_endpoint,
                api_key=api_key,
            )
        else:
            logger.info("Azure OpenAI chat auth mode: Entra ID (DefaultAzureCredential)")
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            self._chat_client = AzureOpenAI(
                azure_deployment=self.chat_model,
                api_version=self.api_version,
                azure_endpoint=self.openai_endpoint,
                azure_ad_token_provider=token_provider,
            )

        return self._chat_client

    def fetch_web_content(self, url: str) -> str:
        """Fetch the text content of a web page, extracting readable text via BeautifulSoup."""
        logger.info(f"Fetching web content from: {url}")
        try:
            with httpx.Client(follow_redirects=True, timeout=30.0) as client:
                response = client.get(url)
                response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove script and style elements
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()

            content = soup.get_text(separator="\n", strip=True)
            logger.debug(f"Fetched {len(content)} characters from {url}")
            return content
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching {url}: {e.response.status_code}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error fetching {url}: {e}")
            raise

    def extract_content(self, classification: str, raw_content: str, description: str = "", objective: str = "") -> str:
        """Extract structured content from raw text using the appropriate prompt for the classification type."""
        prompt = _match_extraction_prompt(classification, objective)
        if not prompt:
            logger.warning(f"No extraction prompt for classification '{classification}', returning raw content")
            return raw_content

        chat_client = self._get_chat_client()
        logger.info(f"Extracting content with classification '{classification}'")

        response = chat_client.chat.completions.create(
            model=self.chat_model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Description: {description}\n\nContent:\n{raw_content}"},
            ],
        )

        extracted = response.choices[0].message.content.strip()
        logger.debug(f"Extracted {len(extracted)} characters for classification '{classification}'")
        return extracted

    def generate_tags(self, content: str, description: str, existing_tags: Optional[List[str]] = None) -> List[str]:
        """Generate descriptive tags from content and description using LLM."""
        chat_client = self._get_chat_client()

        existing_context = ""
        if existing_tags:
            existing_context = f"\n\nExisting tags to preserve: {json.dumps(existing_tags)}"

        response = chat_client.chat.completions.create(
            model=self.chat_model,
            messages=[
                {"role": "system", "content": (
                    "You are a tagging assistant. Given content and a description, "
                    "extract all relevant descriptive terms as tags at most these should be 10 tags. Include technology names, "
                    "company names, industry terms, architecture patterns, key concepts, "
                    "and business terms.\n\n"
                    "Return ONLY a JSON array of lowercase strings, "
                    'e.g. ["azure ai", "multi-agent", "automotive", "data platform"]. '
                    "No explanation, no extra text."
                    + existing_context
                )},
                {"role": "user", "content": f"Description: {description}\n\nContent:\n{content[:4000]}"},
            ],
        )

        try:
            tags_text = response.choices[0].message.content.strip()
            tags = json.loads(tags_text)
            logger.debug(f"Generated {len(tags)} tags")
            return tags
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse tags from LLM response, returning existing tags")
            return existing_tags or []

    def enrich_document(self, document: dict) -> dict:
        """Enrich a document by extracting content from its reference URL.

        Fetches web content if the reference field contains a URL and content is empty,
        extracts structured content using the classification-specific prompt,
        and generates tags.
        """
        classification = document.get("classification", "")
        reference = document.get("reference", "")
        description = document.get("description", "")
        content = document.get("content", "")
        objective = document.get("objective", "")

        # Fetch and extract content if reference URL is present and content is empty
        if reference and not content and _match_extraction_prompt(classification, objective):
            logger.info(f"Enriching document '{document.get('id')}' from reference: {reference}")
            try:
                raw_content = self.fetch_web_content(reference)
                content = self.extract_content(classification, raw_content, description, objective)
                print(f"Extracted content for document '{document.get('id')}': {content[:100]}...")
                document["content"] = content
            except Exception as e:
                logger.error(f"Failed to enrich document '{document.get('id')}': {e}")
                content = description

        # Generate tags if content was extracted
        if content and _match_extraction_prompt(classification, objective):
            existing_tags = document.get("tags", [])
            document["tags"] = self.generate_tags(content, description, existing_tags)

        return document

    def enrich_documents(self, documents: List[dict]) -> List[dict]:
        """Enrich a list of documents with extracted content and embeddings."""
        logger.info(f"Enriching {len(documents)} documents")
        enriched = []
        for i, doc in enumerate(documents):
            logger.debug(f"Processing document {i + 1}/{len(documents)}: {doc.get('description', 'N/A')[:50]}")
            enriched.append(self.enrich_document(doc))
        logger.info(f"Successfully enriched {len(enriched)} documents")
        return enriched
