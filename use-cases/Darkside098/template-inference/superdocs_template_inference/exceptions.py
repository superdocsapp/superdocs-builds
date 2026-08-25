"""Custom exceptions for the template inference system."""


class TemplateInferenceError(Exception):
    """Base exception for template inference errors."""
    pass


class DocumentLoadError(TemplateInferenceError):
    """Exception raised when document loading fails."""
    pass


class InvalidDocumentError(TemplateInferenceError):
    """Exception raised when document validation fails."""
    pass
