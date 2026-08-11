class DiligenceException(Exception):
    """Base exception for all Diligence application errors."""
    pass

class DuplicateFileError(DiligenceException):
    """Raised when an uploaded document's hash already exists in the database."""
    pass

class UnsupportedFileError(DiligenceException):
    """Raised when an uploaded file format is not supported."""
    pass

class FileIngestionError(DiligenceException):
    """Raised when ingestion process fails during parsing, chunking, or embedding."""
    pass

class DocumentNotFoundError(DiligenceException):
    """Raised when a requested document is not found."""
    pass
