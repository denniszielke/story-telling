"""Ingestion agent — process source URLs into the Azure AI Search index.

Designed to run **inside an Azure Container Apps Sandbox** (bring-your-own-container).
Given one source URL it:

  1. runs the **asset-identification** skill to classify the URL as
     ``use case`` / ``code`` / ``method`` (objective),
  2. invokes the matching **processing skill** (each objective has its own
     skill) to enrich the asset into an index document, and
  3. embeds and upserts the document into Azure AI Search.

All Azure access uses :class:`DefaultAzureCredential`. Inside the sandbox the
``AZURE_CLIENT_ID`` of the user-assigned managed identity is injected as an env
var, so the agent authenticates as that identity to the Foundry models
(chat + embeddings) and the Azure AI Search index — no secrets in the image.

Usage (inside the sandbox, or locally for testing)::

    python -m src.agents.ingestion.ingestion_agent --url https://example.com/story
    python -m src.agents.ingestion.ingestion_agent --url <url> --objective "use case"

The launcher ``scripts/run_ingestion_sandbox.py`` boots a sandbox per URL and
execs this module for each one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

# Absolute imports so the module works both as ``python -m
# src.agents.ingestion.ingestion_agent`` and inside the container image.
from src.content.content_internet_extractor import ContentExtractor
from src.content.content_repository_extractor import RepositoryContentExtractor
from src.agents.ingestion.search_index import IngestionSearchIndex
from src.agents.ingestion.skills_runtime import Skill, SkillRegistry

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
_VALID_OBJECTIVES = {"use case", "code", "method"}


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _stable_id(url: str) -> str:
    """Deterministic document id from the URL so re-ingesting merges in place."""
    return hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:16]


def _coerce_json(text: str) -> dict:
    """Best-effort parse of a JSON object out of an LLM response."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


class IngestionAgent:
    """Skill-driven agent that turns a URL into an indexed document."""

    def __init__(self) -> None:
        self.openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.chat_model = os.getenv("AZURE_OPENAI_LARGE_CHAT_DEPLOYMENT_NAME", "gpt-5.4")
        self.chat_api_version = os.getenv("OPENAI_API_VERSION", "2024-10-21")

        # Shared extractors (the processing-skill implementations).
        self.content_extractor = ContentExtractor(
            openai_endpoint=self.openai_endpoint,
            chat_model=self.chat_model,
            api_version=self.chat_api_version,
        )
        self.repository_extractor = RepositoryContentExtractor(
            openai_endpoint=self.openai_endpoint,
            chat_model=self.chat_model,
            api_version=self.chat_api_version,
        )

        self.skills = SkillRegistry(_SKILLS_DIR).load()
        self.index = IngestionSearchIndex(openai_endpoint=self.openai_endpoint)

        self._chat_client: Optional[AzureOpenAI] = None

    # -- LLM client (for the identification skill) -----------------------------

    def _chat(self) -> AzureOpenAI:
        if self._chat_client:
            return self._chat_client
        api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
        if api_key:
            self._chat_client = AzureOpenAI(
                azure_deployment=self.chat_model,
                api_version=self.chat_api_version,
                azure_endpoint=self.openai_endpoint,
                api_key=api_key,
            )
        else:
            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
            )
            self._chat_client = AzureOpenAI(
                azure_deployment=self.chat_model,
                api_version=self.chat_api_version,
                azure_endpoint=self.openai_endpoint,
                azure_ad_token_provider=token_provider,
            )
        return self._chat_client

    # -- Skill: asset identification -------------------------------------------

    def identify(self, url: str, page_text: str, skill: Skill) -> dict:
        """Run the asset-identification skill to classify the URL."""
        user_payload = (
            f"URL: {url}\n\n"
            f"Page text (truncated):\n{(page_text or '')[:6000]}"
        )
        response = self._chat().chat.completions.create(
            model=self.chat_model,
            messages=[
                {"role": "system", "content": skill.instructions},
                {"role": "user", "content": user_payload},
            ],
        )
        raw = response.choices[0].message.content
        result = _coerce_json(raw)

        objective = str(result.get("objective", "")).strip().lower()
        if objective not in _VALID_OBJECTIVES:
            raise ValueError(f"Identification returned invalid objective '{objective}' for {url}")
        result["objective"] = objective
        result.setdefault("classification", "")
        result.setdefault("description", url)
        result.setdefault("source", "internet")
        return result

    # -- Skill: processing (dispatch by processor strategy) --------------------

    def process(self, document: dict, skill: Skill) -> dict:
        """Enrich the base document using the processor the skill declares."""
        processor = skill.processor
        logger.info("Processing '%s' with skill '%s' (processor=%s)", document.get("reference"), skill.name, processor)

        if processor == "repository":
            enriched = self.repository_extractor.enrich_documents([document])[0]
        elif processor in {"case-study", "concept"}:
            enriched = self.content_extractor.enrich_document(document)
        else:
            raise RuntimeError(f"Skill '{skill.name}' declares unknown processor '{processor}'")
        return enriched

    # -- End-to-end ------------------------------------------------------------

    def process_url(self, url: str, objective_override: Optional[str] = None) -> dict:
        url = url.strip()
        print(f"\n=== Ingesting: {url} ===")

        # 1. Fetch readable page text (best-effort — repos may be sparse).
        page_text = ""
        try:
            page_text = self.content_extractor.fetch_web_content(url)
        except Exception as exc:  # noqa: BLE001 - classification can still proceed
            logger.warning("Could not fetch page text for %s: %s", url, exc)

        # 2. Identify the asset objective via the identification skill.
        if objective_override:
            objective = objective_override.strip().lower()
            if objective not in _VALID_OBJECTIVES:
                raise ValueError(f"--objective must be one of {sorted(_VALID_OBJECTIVES)}")
            identity = {
                "objective": objective,
                "classification": "",
                "description": url,
                "source": "internet",
            }
            print(f"  • objective (override): {objective}")
        else:
            id_skill = self.skills.identification_skill
            identity = self.identify(url, page_text, id_skill)
            print(f"  • objective: {identity['objective']}  ({identity.get('classification', '')})")

        # 3. Build the base document (mirrors the index schema).
        today = _utc_today()
        document = {
            "id": _stable_id(url),
            "objective": identity["objective"],
            "description": identity.get("description") or url,
            "created": today,
            "updated": today,
            "scenario": "",
            "context": identity.get("classification", ""),
            "content": "",
            "source": identity.get("source", "internet"),
            "reference": url,
            "classification": identity.get("classification", ""),
            "complexity": identity.get("complexity", ""),
            "tags": identity.get("tags", []),
            "rating": identity.get("rating"),
            "artifacts": [],
        }

        # 4. Invoke the matching processing skill.
        processing_skill = self.skills.processing_skill_for(identity["objective"])
        print(f"  • processing skill: {processing_skill.name}")
        document = self.process(document, processing_skill)

        # 5. Embed + upsert into Azure AI Search.
        print("  • upserting into Azure AI Search…")
        self.index.upsert_documents([document])

        # Strip vectors before returning/printing.
        document.pop("scenario_vector", None)
        document.pop("content_vector", None)
        print(f"  ✅ Indexed '{document['id']}' (objective={document['objective']})")
        return document


def _read_urls(args: argparse.Namespace) -> list[str]:
    if args.url:
        return [args.url]
    if args.urls:
        return [u.strip() for u in args.urls.replace(",", " ").split() if u.strip()]
    if args.urls_file:
        raw = Path(args.urls_file).read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return [line.strip() for line in raw.splitlines() if line.strip()]
        if isinstance(data, list):
            out = []
            for item in data:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict) and item.get("reference"):
                    out.append(item["reference"])
            return out
    return []


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest source URLs into Azure AI Search.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="A single source URL to ingest.")
    group.add_argument("--urls", help="Comma/space-separated list of URLs.")
    group.add_argument("--urls-file", help="Path to a JSON array / newline list of URLs.")
    parser.add_argument(
        "--objective",
        choices=sorted(_VALID_OBJECTIVES),
        help="Skip identification and force this objective.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    urls = _read_urls(args)
    if not urls:
        sys.exit("❌ No URLs provided.")

    agent = IngestionAgent()
    failures = 0
    for url in urls:
        try:
            agent.process_url(url, objective_override=args.objective)
        except Exception as exc:  # noqa: BLE001 - one bad URL shouldn't abort the batch
            failures += 1
            logger.exception("Failed to ingest %s: %s", url, exc)
            print(f"  ❌ Failed to ingest {url}: {exc}")

    print(f"\nDone. {len(urls) - failures}/{len(urls)} URL(s) ingested.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
