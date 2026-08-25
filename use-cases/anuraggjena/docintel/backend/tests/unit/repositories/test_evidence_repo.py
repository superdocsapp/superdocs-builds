def test_evidence_repository_importable():
    from backend.repositories.evidence import EvidenceRepository, CitationRepository
    assert EvidenceRepository is not None
    assert CitationRepository is not None


def test_evidence_repository_is_base_repository():
    from backend.repositories.evidence import EvidenceRepository
    from backend.repositories.base import BaseRepository
    assert issubclass(EvidenceRepository, BaseRepository)


def test_citation_repository_is_base_repository():
    from backend.repositories.evidence import CitationRepository
    from backend.repositories.base import BaseRepository
    assert issubclass(CitationRepository, BaseRepository)
