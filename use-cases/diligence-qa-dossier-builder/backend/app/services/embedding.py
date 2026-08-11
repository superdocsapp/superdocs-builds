import re
import hashlib
import random
from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel

from backend.app.config import settings

class EmbeddingService(ABC):
    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for a single text chunk."""
        pass

    @abstractmethod
    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple text chunks."""
        pass

# Standard stop words to filter out noise from function words
STOP_WORDS = {
    "what", "is", "the", "and", "of", "in", "on", "at", "to", "for", "with", 
    "a", "an", "who", "whom", "they", "them", "do", "does", "did", "how", 
    "why", "whose", "this", "that", "these", "those", "are", "was", "were", 
    "be", "been", "being", "have", "has", "had", "by", "from", "about", "as",
    "company", "companys", "acme", "corporation", "firm"
}

class MockEmbeddingService(EmbeddingService):
    def __init__(self, dimension: int = 1536):
        self.dimension = dimension

    async def get_embedding(self, text: str) -> List[float]:
        """
        Generates a deterministic vector of floats based on the sum of 
        deterministic word-level vectors, filtering out stop words.
        """
        def stem_word(word: str) -> str:
            word = word.lower().strip()
            if len(word) > 4:
                if word.endswith("ies"):
                    return word[:-3] + "y"
                if word.endswith("s") and not word.endswith("ss"):
                    return word[:-1]
                if word.endswith("ing"):
                    return word[:-3]
                if word.endswith("ed"):
                    return word[:-2]
            return word

        # Clean and split text into lowercase words
        cleaned = re.sub(r"[^\w\s]", "", text.lower())
        words = cleaned.split()
        
        # Filter stop words and stem to keep only semantic tokens
        semantic_words = [stem_word(w) for w in words if w not in STOP_WORDS]
        
        if not semantic_words:
            semantic_words = [stem_word(words[0])] if words else ["empty"]

        final_vector = [0.0] * self.dimension

        # Concept index boosting for due diligence queries:
        # 0: ARR
        # 1: Revenue
        # 2: Gross Margin
        # 3: Employee count / headcount
        # 4: Major customers / clients
        # 5: Legal / operational risks
        # 6: Security / SOC 2 certifications
        CONCEPT_MAP = {
            0: ["arr", "annual recurring revenue", "recurring revenue"],
            1: ["revenue", "sales", "turnover", "inflow", "financials", "financial", "income", "profit"],
            2: ["gross margin", "margin", "gross profit", "margins", "profit margin"],
            3: ["employee", "headcount", "workforce", "people", "staff", "hired", "engineer", "success", "support", "engineering", "personnel", "hiring"],
            4: ["customer", "client", "concentration", "globaltech", "finserve", "retailhub", "contract", "retention"],
            5: ["litigation", "lawsuit", "pending", "court", "legal", "claims", "liability", "liabilities", "risk", "operational", "material", "operating burn", "runway", "breach"],
            6: ["soc 2", "soc2", "certification", "audit", "patched", "vulnerability", "encryption", "secure", "security", "gdpr", "vuln"],
            7: ["own", "share", "cap table", "holding", "equity", "founder", "john doe"]
        }
        
        text_lower = text.lower()
        for idx, keywords in CONCEPT_MAP.items():
            for kw in keywords:
                if kw in text_lower:
                    final_vector[idx] = 20.0
                    break

        # Accumulate word-level vectors in the remaining dimensions (index 10+)
        for word in semantic_words:
            hasher = hashlib.md5(word.encode("utf-8"))
            seed = int(hasher.hexdigest(), 16) % (2**32)
            
            rng = random.Random(seed)
            # Scale down components to [-0.1, 0.1] to prevent massive norm dilution on larger text files
            word_vector = [rng.uniform(-0.1, 0.1) for _ in range(self.dimension)]
            
            for i in range(10, self.dimension):
                final_vector[i] += word_vector[i]

        # Normalize the accumulated vector
        norm = sum(x * x for x in final_vector) ** 0.5
        if norm > 0:
            final_vector = [x / norm for x in final_vector]
            
        return final_vector

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        return [await self.get_embedding(text) for text in texts]

def get_embedding_service() -> EmbeddingService:
    """
    Factory function loading the configured embedding provider.
    """
    provider = settings.EMBEDDING_PROVIDER.lower()
    if provider == "mock":
        return MockEmbeddingService(dimension=settings.EMBEDDING_DIMENSION)
    else:
        raise ValueError(f"Unsupported embedding provider configured: {settings.EMBEDDING_PROVIDER}")
