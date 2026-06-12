import json
import logging
import os
import re
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from openai import AzureOpenAI

from .content_internet_extractor import load_prompt

load_dotenv()

logger = logging.getLogger(__name__)

SCENARIO_SECTION_TITLES = {
    "scenario",
    "scenario description and customer context",
    "scenario description and problem space",
}


class RepositoryContentExtractor:
    """Extract repository-focused content using GitHub metadata and default README only."""

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
        self._prompt_template = load_prompt("repository-extraction.md")

    def _get_chat_client(self) -> AzureOpenAI:
        if self._chat_client:
            return self._chat_client

        api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
        if api_key:
            self._chat_client = AzureOpenAI(
                azure_deployment=self.chat_model,
                api_version=self.api_version,
                azure_endpoint=self.openai_endpoint,
                api_key=api_key,
            )
        else:
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

    def _parse_github_repo(self, url: str) -> Optional[tuple[str, str]]:
        parsed = urlparse((url or "").strip())
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            return None

        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2:
            return None

        owner, repo = path_parts[0], path_parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]

        return owner, repo

    def _extract_markdown_section(self, markdown: str, section_titles: set[str]) -> str:
        heading_pattern = re.compile(r"^#{1,6}\\s+(.+?)\\s*$", re.MULTILINE)
        matches = list(heading_pattern.finditer(markdown or ""))

        for index, match in enumerate(matches):
            title = match.group(1).strip().lower()
            if title not in section_titles:
                continue

            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
            return markdown[start:end].strip("\\n -")

        return ""

    def _remove_markdown_section(self, markdown: str, section_titles: set[str]) -> str:
        heading_pattern = re.compile(r"^#{1,6}\\s+(.+?)\\s*$", re.MULTILINE)
        matches = list(heading_pattern.finditer(markdown or ""))

        for index, match in enumerate(matches):
            title = match.group(1).strip().lower()
            if title not in section_titles:
                continue

            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
            before = markdown[:start].rstrip()
            after = markdown[end:].lstrip()
            return f"{before}\\n\\n{after}".strip()

        return markdown.strip()

    def _trim_markdown_preamble(self, markdown: str) -> str:
        heading_match = re.search(r"^#{1,6}\\s+.+$", markdown or "", re.MULTILINE)
        if not heading_match:
            return markdown.strip()
        return markdown[heading_match.start():].strip()

    def _fetch_repository_snapshot(self, owner: str, repo: str) -> dict:
        base_url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "story-telling-indexer",
        }

        with httpx.Client(follow_redirects=True, timeout=30.0, headers=headers) as client:
            repo_response = client.get(base_url)
            repo_response.raise_for_status()
            repo_data = repo_response.json()

            readme_response = client.get(
                f"{base_url}/readme",
                headers={**headers, "Accept": "application/vnd.github.raw"},
            )
            readme_text = ""
            if readme_response.status_code == 200:
                readme_text = readme_response.text

        return {
            "name": repo_data.get("name"),
            "full_name": repo_data.get("full_name"),
            "description": repo_data.get("description") or "",
            "html_url": repo_data.get("html_url"),
            "language": repo_data.get("language") or "",
            "topics": repo_data.get("topics") or [],
            "stargazers_count": repo_data.get("stargazers_count"),
            "forks_count": repo_data.get("forks_count"),
            "open_issues_count": repo_data.get("open_issues_count"),
            "watchers_count": repo_data.get("watchers_count"),
            "default_branch": repo_data.get("default_branch"),
            "license": (repo_data.get("license") or {}).get("spdx_id") or "",
            "created_at": repo_data.get("created_at"),
            "updated_at": repo_data.get("updated_at"),
            "pushed_at": repo_data.get("pushed_at"),
            "archived": repo_data.get("archived"),
            "homepage": repo_data.get("homepage") or "",
            "readme": readme_text,
        }

    def _extract_repository_content(self, snapshot: dict, description: str) -> str:
        metadata_payload = {
            "full_name": snapshot.get("full_name"),
            "description": snapshot.get("description") or description,
            "language": snapshot.get("language"),
            "topics": snapshot.get("topics", []),
            "stars": snapshot.get("stargazers_count"),
            "forks": snapshot.get("forks_count"),
            "open_issues": snapshot.get("open_issues_count"),
            "watchers": snapshot.get("watchers_count"),
            "default_branch": snapshot.get("default_branch"),
            "license": snapshot.get("license"),
            "created_at": snapshot.get("created_at"),
            "updated_at": snapshot.get("updated_at"),
            "pushed_at": snapshot.get("pushed_at"),
            "archived": snapshot.get("archived"),
            "homepage": snapshot.get("homepage"),
        }
        readme = (snapshot.get("readme") or "")[:30000]

        user_payload = (
            f"Repository metadata:\n{json.dumps(metadata_payload, ensure_ascii=True)}\n\n"
            f"Repository description:\n{description or snapshot.get('description', '')}\n\n"
            f"Default README:\n{readme}"
        )

        chat_client = self._get_chat_client()
        response = chat_client.chat.completions.create(
            model=self.chat_model,
            messages=[
                {"role": "system", "content": self._prompt_template},
                {"role": "user", "content": user_payload},
            ],
        )
        return response.choices[0].message.content.strip()

    def _merge_tags(self, existing_tags: List[str], snapshot: dict) -> List[str]:
        merged = {str(tag).strip().lower() for tag in existing_tags if str(tag).strip()}

        language = (snapshot.get("language") or "").strip().lower()
        if language:
            merged.add(language)

        for topic in snapshot.get("topics", []):
            topic_value = str(topic).strip().lower()
            if topic_value:
                merged.add(topic_value)

        merged.add("github")
        return sorted(merged)

    def _is_repository_document(self, document: dict) -> bool:
        objective = (document.get("objective") or "").strip().lower()
        reference = (document.get("reference") or "").strip().lower()

        if objective == "code":
            return True
        return "github.com/" in reference

    def enrich_document(self, document: dict) -> dict:
        if not self._is_repository_document(document):
            return document

        reference = document.get("reference", "")
        parsed = self._parse_github_repo(reference)
        if not parsed:
            logger.warning("Skipping repository enrichment for unsupported URL: %s", reference)
            return document

        owner, repo = parsed
        logger.info("Enriching repository document '%s' from %s/%s", document.get("id"), owner, repo)

        try:
            snapshot = self._fetch_repository_snapshot(owner, repo)
            extracted = self._extract_repository_content(snapshot, document.get("description", ""))

            scenario = self._extract_markdown_section(extracted, SCENARIO_SECTION_TITLES)
            content = self._trim_markdown_preamble(
                self._remove_markdown_section(extracted, SCENARIO_SECTION_TITLES)
            )

            if scenario:
                document["scenario"] = scenario
            elif not document.get("scenario"):
                document["scenario"] = document.get("description", "")

            if content:
                document["content"] = content

            existing_tags = document.get("tags", []) or []
            document["tags"] = self._merge_tags(existing_tags, snapshot)

            # Add deterministic language metadata signal for retrieval without changing schema.
            language = snapshot.get("language") or ""
            if language and language.lower() not in (document.get("content", "").lower()):
                document["content"] = (
                    f"Primary language: {language}.\\n\\n{document.get('content', '')}"
                ).strip()

        except Exception as exc:
            logger.error("Failed to enrich repository document '%s': %s", document.get("id"), exc)

        return document

    def enrich_documents(self, documents: List[dict]) -> List[dict]:
        enriched = []
        for document in documents:
            enriched.append(self.enrich_document(document))
        return enriched
