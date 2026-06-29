"""Single-document Azure AI Search upsert for the ingestion agent.

Copied and trimmed from ``scripts/search_index_pipeline.py`` so the ingestion
agent can run **inside a container/sandbox** without the rest of the pipeline.
It keeps the exact same index schema (fields + vector profiles) and embedding
logic, but exposes a focused ``upsert_documents`` entry point that:

  * ensures the index exists (idempotent ``create_or_update_index``),
  * guarantees a ``scenario`` for objectives that require one,
  * generates ``scenario_vector`` / ``content_vector`` embeddings, and
  * merges the document(s) into the index.

Authentication is via :class:`DefaultAzureCredential`. Inside the sandbox the
``AZURE_CLIENT_ID`` of the user-assigned managed identity is injected as an env
var, so the credential authenticates as that identity to both Azure OpenAI
(embeddings) and Azure AI Search (index management + data plane).
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    ComplexField,
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    VectorSearch,
    VectorSearchProfile,
)
from openai import AzureOpenAI

logger = logging.getLogger(__name__)


class IngestionSearchIndex:
    """Ensure the search index exists and upsert enriched documents with embeddings."""

    def __init__(
        self,
        index_name: Optional[str] = None,
        search_endpoint: Optional[str] = None,
        openai_endpoint: Optional[str] = None,
        embedding_model: Optional[str] = None,
        embedding_dimensions: Optional[int] = None,
        api_version: Optional[str] = None,
    ):
        self.index_name = index_name or os.getenv("AZURE_AI_SEARCH_INDEX_NAME", "kusto-queries-index")
        self.search_endpoint = search_endpoint or os.getenv("AZURE_AI_SEARCH_ENDPOINT")
        self.openai_endpoint = openai_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.embedding_model = embedding_model or os.getenv(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small"
        )
        self.embedding_dimensions = embedding_dimensions or int(
            os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536")
        )
        self.api_version = api_version or os.getenv("AZURE_OPENAI_EMBEDDING_API_VERSION", "2024-10-21")

        self._credential = None
        self._index_client: Optional[SearchIndexClient] = None
        self._search_client: Optional[SearchClient] = None
        self._openai_client: Optional[AzureOpenAI] = None

        logger.info(
            "IngestionSearchIndex initialized: index='%s', endpoint='%s'",
            self.index_name,
            self.search_endpoint,
        )

    # -- credentials / clients -------------------------------------------------

    def _get_credential(self):
        if self._credential is None:
            self._credential = DefaultAzureCredential()
        return self._credential

    def _get_openai_client(self) -> AzureOpenAI:
        if self._openai_client:
            return self._openai_client

        api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
        if api_key:
            self._openai_client = AzureOpenAI(
                azure_deployment=self.embedding_model,
                api_version=self.api_version,
                azure_endpoint=self.openai_endpoint,
                api_key=api_key,
            )
        else:
            token_provider = get_bearer_token_provider(
                self._get_credential(), "https://cognitiveservices.azure.com/.default"
            )
            self._openai_client = AzureOpenAI(
                azure_deployment=self.embedding_model,
                api_version=self.api_version,
                azure_endpoint=self.openai_endpoint,
                azure_ad_token_provider=token_provider,
            )
        return self._openai_client

    def _get_index_client(self) -> SearchIndexClient:
        if self._index_client:
            return self._index_client
        if not self.search_endpoint:
            raise ValueError("AZURE_AI_SEARCH_ENDPOINT environment variable is not set")
        self._index_client = SearchIndexClient(
            endpoint=self.search_endpoint, credential=self._get_credential()
        )
        return self._index_client

    def _get_search_client(self) -> SearchClient:
        if self._search_client:
            return self._search_client
        if not self.search_endpoint:
            raise ValueError("AZURE_AI_SEARCH_ENDPOINT environment variable is not set")
        self._search_client = SearchClient(
            endpoint=self.search_endpoint,
            index_name=self.index_name,
            credential=self._get_credential(),
        )
        return self._search_client

    # -- scenario guarantees (mirrors the pipeline) ----------------------------

    def _requires_scenario(self, doc: dict) -> bool:
        objective = (doc.get("objective") or "").strip().lower()
        return objective in {"use case", "method"}

    def _build_fallback_scenario(self, doc: dict) -> str:
        parts = []
        description = (doc.get("description") or "").strip()
        if description:
            parts.append(description)
        context = (doc.get("context") or "").strip()
        if context:
            parts.append(f"Context: {context}.")
        classification = (doc.get("classification") or "").strip()
        if classification:
            parts.append(f"Classification: {classification}.")
        return " ".join(parts).strip()

    def _ensure_required_scenario(self, doc: dict) -> dict:
        scenario = (doc.get("scenario") or "").strip()
        if not self._requires_scenario(doc):
            if scenario:
                doc["scenario"] = scenario
            return doc
        if not scenario:
            scenario = self._build_fallback_scenario(doc)
        if not scenario:
            raise ValueError(
                f"Document '{doc.get('id')}' requires a scenario but none could be derived"
            )
        doc["scenario"] = scenario
        return doc

    # -- embeddings ------------------------------------------------------------

    def _generate_embedding(self, text: str) -> List[float]:
        client = self._get_openai_client()
        response = client.embeddings.create(
            input=text,
            model=self.embedding_model,
            dimensions=self.embedding_dimensions,
        )
        return response.data[0].embedding

    # -- index management ------------------------------------------------------

    def ensure_index(self) -> None:
        """Create the search index if it doesn't already exist (idempotent)."""
        index_client = self._get_index_client()
        existing = {idx.name for idx in index_client.list_indexes()}
        action = "updated" if self.index_name in existing else "created"

        fields = [
            SearchField(name="id", type=SearchFieldDataType.String, key=True),
            SearchField(name="objective", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True),
            SearchField(name="description", type=SearchFieldDataType.String, searchable=True),
            SearchField(name="created", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
            SearchField(name="updated", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
            SearchField(name="scenario", type=SearchFieldDataType.String, searchable=True),
            SearchField(name="context", type=SearchFieldDataType.String, searchable=True),
            SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
            SearchField(name="source", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True),
            SearchField(name="reference", type=SearchFieldDataType.String, searchable=True),
            SearchField(name="classification", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True),
            SearchField(name="complexity", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True),
            SearchField(name="tags", type="Collection(Edm.String)", hidden=False, filterable=True, sortable=False, facetable=True, searchable=True),
            SearchField(name="rating", type=SearchFieldDataType.Double, filterable=True, sortable=True),
            ComplexField(name="artifacts", collection=True, fields=[
                SearchField(name="description", type=SearchFieldDataType.String, searchable=True),
                SearchField(name="type", type=SearchFieldDataType.String, searchable=True, filterable=True),
                SearchField(name="reference", type=SearchFieldDataType.String, searchable=True),
            ]),
            SearchField(
                name="scenario_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                vector_search_dimensions=self.embedding_dimensions,
                vector_search_profile_name="hnsw",
            ),
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                vector_search_dimensions=self.embedding_dimensions,
                vector_search_profile_name="hnsw",
            ),
        ]

        vector_search = VectorSearch(
            profiles=[VectorSearchProfile(name="hnsw", algorithm_configuration_name="hnsw")],
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        )

        index = SearchIndex(name=self.index_name, fields=fields, vector_search=vector_search)
        result = index_client.create_or_update_index(index)
        logger.info("Index '%s' %s.", result.name, action)
        print(f"Index '{result.name}' {action}.")

    # -- upsert ----------------------------------------------------------------

    def upsert_documents(self, docs: List[dict]) -> int:
        """Embed and merge-or-upload the given documents. Returns succeeded count."""
        if not docs:
            return 0

        self.ensure_index()
        search_client = self._get_search_client()

        prepared: List[dict] = []
        for doc in docs:
            doc = self._ensure_required_scenario(doc)
            scenario_text = (doc.get("scenario") or "").strip()
            if scenario_text:
                doc["scenario"] = scenario_text
                doc["scenario_vector"] = self._generate_embedding(scenario_text)
            embedding_text = doc.get("content") or doc.get("description", "")
            if embedding_text:
                doc["content_vector"] = self._generate_embedding(embedding_text)
            prepared.append(doc)

        result = search_client.merge_or_upload_documents(documents=prepared)
        succeeded = sum(1 for r in result if r.succeeded)
        failed = len(prepared) - succeeded
        if failed:
            logger.warning("Upsert completed with %d failures (%d/%d)", failed, succeeded, len(prepared))
        else:
            logger.info("Upserted all %d document(s) to index '%s'", succeeded, self.index_name)
        print(f"Upserted {succeeded}/{len(prepared)} document(s) to index '{self.index_name}'.")
        return succeeded
