"""Abstract base class for document loaders."""

from abc import ABC, abstractmethod

from superdocs_template_inference.models import Document


class DocumentLoader(ABC):
    """Abstract base class for document loaders.
    
    Subclasses must implement the load() method to handle
    a specific file format and return a normalized Document.
    """

    @abstractmethod
    def load(self, file_path: str) -> Document:
        """Load and normalize a document from the given file path.
        
        Args:
            file_path: Path to the document file.
            
        Returns:
            A normalized Document object.
            
        Raises:
            DocumentLoadError: If the document cannot be loaded or parsed.
        """
        pass
