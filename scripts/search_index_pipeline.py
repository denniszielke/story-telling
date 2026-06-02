import json
import logging
import os
import sys
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchField,
    SearchFieldDataType,
    HnswAlgorithmConfiguration,
    VectorSearch,
    VectorSearchProfile,
    SearchIndex,
)
from azure.search.documents import SearchClient
from openai import AzureOpenAI
from dotenv import load_dotenv

from src.content.content_extractor import ContentExtractor

load_dotenv()

logger = logging.getLogger(__name__)

logging.getLogger('azure.core.pipeline.policies.http_logging_policy').setLevel(logging.WARNING)
logging.getLogger('azure.monitor.opentelemetry.exporter.export').setLevel(logging.WARNING)
logging.getLogger('azure.identity').setLevel(logging.WARNING)

class SearchIndexMaintainer:
    """Manages Azure AI Search index creation and document ingestion with embeddings."""
    
    def __init__(
        self,
        index_name: Optional[str] = None,
        search_endpoint: Optional[str] = None,
        openai_endpoint: Optional[str] = None,
        embedding_model: Optional[str] = None,
        embedding_dimensions: Optional[int] = None,
        chat_model: Optional[str] = None,
        api_version: Optional[str] = None,
        query_samples_path: Optional[str] = None,
    ):
        """Initialize the SearchIndexMaintainer with configuration from environment or parameters."""
        self.index_name = index_name or os.getenv("AZURE_AI_SEARCH_INDEX_NAME", "kusto-queries-index")
        self.search_endpoint = search_endpoint or os.getenv("AZURE_AI_SEARCH_ENDPOINT")
        self.openai_endpoint = openai_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.embedding_model = embedding_model or os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small")
        self.embedding_dimensions = embedding_dimensions or int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536"))
        self.api_version = api_version or os.getenv("AZURE_OPENAI_EMBEDDING_API_VERSION", "2024-10-21")
        self.query_samples_path = query_samples_path or os.path.join(os.path.dirname(__file__), "..", "data", "query-samples.json")
        
        self._credential = None
        self._index_client = None
        self._search_client = None
        self._openai_client = None

        self._content_extractor = ContentExtractor(
            openai_endpoint=openai_endpoint,
            chat_model=chat_model,
            api_version=api_version,
        )
        
        logger.info(f"Initialized SearchIndexMaintainer: index='{self.index_name}', endpoint='{self.search_endpoint}'")
    
    def _get_credential(self):
        """Get Azure AI Search credential (API key or Entra ID)."""
        if self._credential:
            return self._credential

        self._credential = DefaultAzureCredential()
        logger.debug("Search credential type: %s", type(self._credential).__name__)
        return self._credential
    
    def _get_openai_client(self) -> AzureOpenAI:
        """Create or return the Azure OpenAI embedding client."""
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
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            self._openai_client = AzureOpenAI(
                azure_deployment=self.embedding_model,
                api_version=self.api_version,
                azure_endpoint=self.openai_endpoint,
                azure_ad_token_provider=token_provider,
            )

        return self._openai_client

    def _generate_embedding(self, text: str) -> List[float]:
        """Generate an embedding vector for the given text."""
        client = self._get_openai_client()
        response = client.embeddings.create(
            input=text,
            model=self.embedding_model,
            dimensions=self.embedding_dimensions,
        )
        return response.data[0].embedding
    
    def _get_index_client(self) -> SearchIndexClient:
        """Get or create SearchIndexClient."""
        if self._index_client:
            return self._index_client
        
        if not self.search_endpoint:
            logger.error("AZURE_AI_SEARCH_ENDPOINT environment variable is not set")
            raise ValueError("AZURE_AI_SEARCH_ENDPOINT environment variable is not set")
        
        logger.debug(f"Creating SearchIndexClient for endpoint: {self.search_endpoint}")
        credential = self._get_credential()
        self._index_client = SearchIndexClient(endpoint=self.search_endpoint, credential=credential)
        logger.info("SearchIndexClient created successfully")
        return self._index_client
    
    def _get_search_client(self) -> SearchClient:
        """Get or create SearchClient."""
        if self._search_client:
            return self._search_client
        
        if not self.search_endpoint:
            logger.error("AZURE_AI_SEARCH_ENDPOINT environment variable is not set")
            raise ValueError("AZURE_AI_SEARCH_ENDPOINT environment variable is not set")
        
        logger.debug(f"Creating SearchClient for index: {self.index_name}")
        credential = self._get_credential()
        self._search_client = SearchClient(
            endpoint=self.search_endpoint,
            index_name=self.index_name,
            credential=credential
        )
        logger.info(f"SearchClient created successfully for index '{self.index_name}'")
        return self._search_client
    
    def ensure_index(self):
        """Create the search index if it doesn't already exist."""
        logger.info(f"Ensuring index '{self.index_name}' exists...")
        index_client = self._get_index_client()
        
        # Check if index already exists
        logger.debug("Checking for existing indexes...")
        existing_indexes = [idx.name for idx in index_client.list_indexes()]
        if self.index_name in existing_indexes:
            logger.info(f"Index '{self.index_name}' already exists.")
            print(f"Index '{self.index_name}' already exists.")
            return

        fields = [
            SearchField(name="id", type=SearchFieldDataType.String, key=True),
            SearchField(name="objective", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True), 
            SearchField(name="description", type=SearchFieldDataType.String, searchable=True),
            SearchField(name="created", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
            SearchField(name="updated", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
            SearchField(name="context", type=SearchFieldDataType.String, searchable=True),
            SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
            SearchField(name="source", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True),
            SearchField(name="reference", type=SearchFieldDataType.String, searchable=True),
            SearchField(name="classification", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True),
            SearchField(name="complexity", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True),
            SearchField(name="tags", type="Collection(Edm.String)", hidden=False, filterable=True, sortable=False, facetable=True, searchable=True),
            SearchField(name="rating", type=SearchFieldDataType.Double, filterable=True, sortable=True),
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                vector_search_dimensions=self.embedding_dimensions,
                vector_search_profile_name="hnsw"
            )
        ]
        
        vector_search = VectorSearch(
            profiles=[VectorSearchProfile(name="hnsw", algorithm_configuration_name="hnsw")],
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        )
        
        logger.debug(f"Creating new index '{self.index_name}' with {len(fields)} fields and vector search configuration")
        index = SearchIndex(name=self.index_name, fields=fields, vector_search=vector_search)
        result = index_client.create_or_update_index(index)
        logger.info(f"Index '{result.name}' created successfully.")
        print(f"Index '{result.name}' created.")
    
    def load_samples_from_json(self, payload: List[dict]) -> List[dict]:
        """Load documents from JSON payload and enrich them with content extraction and embeddings."""
        logger.info(f"Loading {len(payload)} samples from JSON payload")
        
        docs = []
        for i, item in enumerate(payload):
            logger.debug(f"Processing sample {i+1}/{len(payload)}: {item.get('description', 'N/A')[:50]}...")
            doc = {
                "id": item.get("id") or str(i),
                "objective": item.get("objective", ""),
                "description": item.get("description", ""),
                "created": item.get("created"),
                "updated": item.get("updated"),
                "context": item.get("context", ""),
                "content": item.get("content", ""),
                "source": item.get("source", ""),
                "reference": item.get("reference", ""),
                "classification": item.get("classification", ""),
                "complexity": item.get("complexity", ""),
                "tags": item.get("tags", []),
                "rating": item.get("rating"),
            }
            docs.append(doc)

        # Enrich all documents via the content extractor
        docs = self._content_extractor.enrich_documents(docs)

        # Generate embeddings (search-indexing concern)
        for doc in docs:
            embedding_text = doc.get("content") or doc.get("description", "")
            if embedding_text:
                doc["content_vector"] = self._generate_embedding(embedding_text)
        
        logger.info(f"Successfully loaded {len(docs)} documents with embeddings")
        return docs

    def load_samples_from_file(self, path: Optional[str] = None) -> List[dict]:
        """Load query samples from JSON file and generate embeddings."""
        file_path = path or self.query_samples_path
        logger.info(f"Loading samples from file: {file_path}")
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.debug(f"Loaded {len(data)} samples from file")
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file {file_path}: {e}")
            raise
        
        docs = self.load_samples_from_json(data)
        
        return docs
    
    def upload_samples_from_json(self, payload):
        """Upload query samples from JSON string to the search index."""
        logger.info("Starting upload process from JSON payload")
        self.ensure_index()
        search_client = self._get_search_client()
        
        docs = self.load_samples_from_json(payload)
        if not docs:
            logger.warning("No documents found in provided JSON payload")
            print("No documents found in provided JSON payload")
            return
        
        logger.info(f"Uploading {len(docs)} documents to index '{self.index_name}'...")
        print(f"Uploading {len(docs)} documents to index '{self.index_name}'...")
        try:
            result = search_client.upload_documents(documents=docs)
            succeeded = sum(1 for r in result if r.succeeded)
            failed = len(docs) - succeeded
            if failed > 0:
                logger.warning(f"Upload completed with {failed} failures: {succeeded}/{len(docs)} documents uploaded")
            else:
                logger.info(f"Successfully uploaded all {succeeded} documents to index '{self.index_name}'")
            print(f"Uploaded {succeeded}/{len(docs)} documents to index '{self.index_name}'.")
        except Exception as e:
            logger.error(f"Failed to upload documents: {e}")
            raise
        
        for doc in docs:
            doc.pop("content_vector", None)  # Remove vector for response

        return {
            "status": "success",
            "filename": "file.filename",
            "query_count": len(docs),
            "queries": docs
        }

    def upload_samples(self, samples_path: Optional[str] = None):
        """Upload query samples to the search index."""
        logger.info("Starting upload process from file")
        self.ensure_index()
        search_client = self._get_search_client()
        
        docs = self.load_samples_from_file(samples_path)
        if not docs:
            logger.warning("No documents found in query-samples.json")
            print("No documents found in query-samples.json")
            return
        
        logger.info(f"Uploading {len(docs)} documents to index '{self.index_name}'...")
        try:
            result = search_client.upload_documents(documents=docs)
            succeeded = sum(1 for r in result if r.succeeded)
            failed = len(docs) - succeeded
            if failed > 0:
                logger.warning(f"Upload completed with {failed} failures: {succeeded}/{len(docs)} documents uploaded")
            else:
                logger.info(f"Successfully uploaded all {succeeded} documents to index '{self.index_name}'")
            print(f"Uploaded {succeeded}/{len(docs)} documents to index '{self.index_name}'.")
        except Exception as e:
            logger.error(f"Failed to upload documents: {e}")
            raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger.info("Starting search index pipeline...")
    maintainer = SearchIndexMaintainer()
    maintainer.upload_samples()
    logger.info("Search index pipeline completed.")
