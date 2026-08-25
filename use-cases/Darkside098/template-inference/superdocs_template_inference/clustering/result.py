"""Clustering result data models."""

from dataclasses import dataclass, field


@dataclass
class FamilyCluster:
    """A detected family cluster of compatible documents."""

    family_id: str  # e.g., "family_001", "family_002"
    document_ids: list[str]  # sorted lexicographically, deterministic
    document_filenames: list[str]  # metadata only, sorted to match document_ids

    confidence: float  # 0.0–1.0, profile-based for singletons, aggregated for multi-doc

    cluster_size: int  # len(document_ids)
    pairwise_scores: list[float]  # all scores within cluster, sorted ascending
    pairwise_score_mean: float  # mean of pairwise_scores
    pairwise_score_min: float  # min of pairwise_scores

    # Evidence for cluster formation
    merge_evidence: list[dict] = field(default_factory=list)


@dataclass
class ClusteringResult:
    """Output from family clustering."""

    clusters: list[FamilyCluster]  # sorted by family_id

    num_clusters: int  # len(clusters)
    num_documents: int  # sum of cluster_sizes

    algorithm: str  # "greedy_agglomerative_complete_linkage"
    threshold_used: float  # compatibility threshold applied

    clustering_version: str = "1.0"

    def get_document_to_cluster_mapping(self) -> dict[str, str]:
        """Return {document_id: family_id} for easy lookup."""
        mapping = {}
        for cluster in self.clusters:
            for doc_id in cluster.document_ids:
                mapping[doc_id] = cluster.family_id
        return mapping
