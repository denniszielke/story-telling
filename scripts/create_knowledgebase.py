"""Create the semantic configuration and agentic-retrieval knowledge base for the
story-telling search index.

This script does two things:

1. Applies (or updates) a **semantic configuration** on the story-telling index so
   that semantic ranking, captions, and answers are available for queries.
2. Creates a **knowledge source** wrapping the index and assembles it into a
   **knowledge base** that can be queried through the Azure AI Search agentic
   retrieval API.

The index field schema mirrors ``scripts/search_index_pipeline.py`` so the
``create_or_update_index`` call is non-destructive: it preserves existing fields
and documents while attaching the semantic configuration.

Environment variables:
  AZURE_AI_SEARCH_ENDPOINT             - e.g. https://<service>.search.windows.net
  AZURE_OPENAI_ENDPOINT                - Azure OpenAI resource endpoint
  AZURE_AI_MODEL_DEPLOYMENT_NAME       - Chat model deployment (default: gpt-4.1-mini)

Optional:
  AZURE_AI_SEARCH_ADMIN_KEY            - Admin API key (falls back to DefaultAzureCredential)
  AZURE_AI_SEARCH_INDEX_NAME           - default: story-telling-index
  AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME  - default: story-telling-kb
  AZURE_OPENAI_EMBEDDING_DIMENSIONS    - default: 1536
"""
from __future__ import annotations

import argparse
import logging
import os

from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizerParameters,
    ComplexField,
    HnswAlgorithmConfiguration,
    KnowledgeBase,
    KnowledgeBaseAzureOpenAIModel,
    KnowledgeSourceReference,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchIndexFieldReference,
    SearchIndexKnowledgeSource,
    SearchIndexKnowledgeSourceParameters,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    VectorSearch,
    VectorSearchProfile,
)
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536"))
SEMANTIC_CONFIG_NAME = "story-telling-semantic"


# ── Clients ──────────────────────────────────────────────────────────────────

def _get_index_client() -> SearchIndexClient:
    endpoint = os.getenv("AZURE_AI_SEARCH_ENDPOINT")
    if not endpoint:
        raise RuntimeError("AZURE_AI_SEARCH_ENDPOINT is required")
    api_key = os.getenv("AZURE_AI_SEARCH_ADMIN_KEY", "").strip()
    credential = AzureKeyCredential(api_key) if api_key else DefaultAzureCredential()
    return SearchIndexClient(endpoint=endpoint, credential=credential)


# ── Search index definition ──────────────────────────────────────────────────

def _hnsw_vector_search() -> VectorSearch:
    return VectorSearch(
        profiles=[VectorSearchProfile(name="hnsw", algorithm_configuration_name="hnsw")],
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
    )


def _build_story_fields() -> list:
    """Story-telling index fields (kept in sync with search_index_pipeline.py)."""
    return [
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
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name="hnsw",
        ),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name="hnsw",
        ),
    ]


def _semantic_search() -> SemanticSearch:
    """Semantic configuration prioritizing the story narrative fields."""
    return SemanticSearch(
        default_configuration_name=SEMANTIC_CONFIG_NAME,
        configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIG_NAME,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="description"),
                    content_fields=[
                        SemanticField(field_name="scenario"),
                        SemanticField(field_name="content"),
                        SemanticField(field_name="context"),
                    ],
                    keywords_fields=[
                        SemanticField(field_name="tags"),
                        SemanticField(field_name="classification"),
                        SemanticField(field_name="objective"),
                    ],
                ),
            )
        ],
    )


def ensure_semantic_configuration(client: SearchIndexClient, index_name: str) -> None:
    """Apply the semantic configuration to the index without dropping data."""
    index = SearchIndex(
        name=index_name,
        fields=_build_story_fields(),
        vector_search=_hnsw_vector_search(),
        semantic_search=_semantic_search(),
    )
    result = client.create_or_update_index(index)
    logger.info("Index '%s' updated with semantic configuration '%s'.", result.name, SEMANTIC_CONFIG_NAME)
    print(f"Index '{result.name}' updated with semantic configuration '{SEMANTIC_CONFIG_NAME}'.")


# ── Knowledge source + knowledge base ────────────────────────────────────────

def _upsert_knowledge_source(client: SearchIndexClient, name: str, index_name: str) -> None:
    """Create or update a searchIndex knowledge source wrapping the index."""
    ks = SearchIndexKnowledgeSource(
        name=name,
        description=(
            "Story-telling repository of customer use cases and methodologies — "
            "covering scenario narratives, context, classification, complexity, and "
            "supporting artifacts for grounded architecture story retrieval."
        ),
        search_index_parameters=SearchIndexKnowledgeSourceParameters(
            search_index_name=index_name,
            source_data_fields=[
                SearchIndexFieldReference(name=f)
                for f in [
                    "id",
                    "objective",
                    "description",
                    "scenario",
                    "context",
                    "content",
                    "classification",
                    "complexity",
                    "tags",
                    "source",
                    "reference",
                    "rating",
                ]
            ],
        ),
    )
    client.create_or_update_knowledge_source(ks)
    logger.info("Knowledge source '%s' created/updated (index: %s).", name, index_name)
    print(f"Knowledge source '{name}' created/updated (index: {index_name}).")


def _upsert_knowledge_base(
    client: SearchIndexClient,
    kb_name: str,
    knowledge_source_name: str,
    aoai_endpoint: str,
    model_deployment_name: str,
) -> None:
    """Create or update the knowledge base aggregating the knowledge source."""
    aoai_params = AzureOpenAIVectorizerParameters(
        resource_url=aoai_endpoint,
        deployment_name=model_deployment_name,
        model_name=model_deployment_name,
    )
    kb = KnowledgeBase(
        name=kb_name,
        description=(
            "Agentic retrieval knowledge base for the story-telling assistant. "
            "Surfaces grounded customer use cases and methodologies to support "
            "architecture proposals and exec-talk preparation."
        ),
        knowledge_sources=[KnowledgeSourceReference(name=knowledge_source_name)],
        models=[KnowledgeBaseAzureOpenAIModel(azure_open_ai_parameters=aoai_params)],
    )
    client.create_or_update_knowledge_base(kb)
    logger.info("Knowledge base '%s' created/updated.", kb_name)
    print(f"Knowledge base '{kb_name}' created/updated.")


# ── Entry point ──────────────────────────────────────────────────────────────

def create_or_update_knowledgebase(
    index_name: str | None = None,
    kb_name: str | None = None,
    aoai_endpoint: str | None = None,
    model_deployment_name: str | None = None,
) -> None:
    index_name = index_name or os.getenv("AZURE_AI_SEARCH_INDEX_NAME", "story-telling-index")
    kb_name = kb_name or os.getenv("AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME", "story-telling-kb")
    aoai_endpoint = aoai_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
    model_deployment_name = model_deployment_name or os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")

    if not aoai_endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is required")

    client = _get_index_client()

    ensure_semantic_configuration(client, index_name)

    knowledge_source_name = f"{index_name}-ks"
    _upsert_knowledge_source(client, name=knowledge_source_name, index_name=index_name)

    _upsert_knowledge_base(
        client,
        kb_name=kb_name,
        knowledge_source_name=knowledge_source_name,
        aoai_endpoint=aoai_endpoint,
        model_deployment_name=model_deployment_name,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create semantic config and knowledge base for the story-telling index")
    parser.add_argument("--index_name", default=None, help="Search index name (default: AZURE_AI_SEARCH_INDEX_NAME or story-telling-index)")
    parser.add_argument("--kb_name", default=None, help="Knowledge base name (default: AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME or story-telling-kb)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    create_or_update_knowledgebase(index_name=args.index_name, kb_name=args.kb_name)


if __name__ == "__main__":
    main()
