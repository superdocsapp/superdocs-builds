"""Grounded manuscript scaffolding business logic."""

from .models import PaperInputs
from .service import ManuscriptService

__all__ = ["ManuscriptService", "PaperInputs"]
