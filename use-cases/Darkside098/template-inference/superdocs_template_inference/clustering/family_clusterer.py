"""Family clustering using greedy agglomerative complete-linkage algorithm."""

from __future__ import annotations

from superdocs_template_inference.compatibility.config import CompatibilityConfig
from superdocs_template_inference.compatibility.scorer import CompatibilityScorer
from superdocs_template_inference.clustering.result import ClusteringResult, FamilyCluster
from superdocs_template_inference.models import DocumentProfile


class FamilyClusterer:
    """Cluster DocumentProfile objects into families using complete-linkage agglomerative clustering."""

    def __init__(self, compatibility_config: CompatibilityConfig | None = None):
        """Initialize clusterer with a compatibility configuration.

        Args:
            compatibility_config: CompatibilityConfig for scoring.
                If None, uses default CompatibilityConfig.
                The threshold value from this config drives all clustering decisions.
        """
        self.compatibility_config = compatibility_config or CompatibilityConfig()
        self.scorer = CompatibilityScorer(self.compatibility_config)

    def cluster(self, profiles: list[DocumentProfile]) -> ClusteringResult:
        """Cluster DocumentProfile objects into families.

        Uses greedy agglomerative clustering with complete linkage (minimum-based).
        Two clusters merge if and only if their minimum inter-cluster pairwise score
        is >= compatibility_threshold.

        Args:
            profiles: List of DocumentProfile objects from profiling stage.

        Returns:
            ClusteringResult with detected families and cluster membership.

        Raises:
            ValueError: If profiles contains duplicate document IDs.
        """
        # Handle empty input
        if not profiles:
            return ClusteringResult(
                clusters=[],
                num_clusters=0,
                num_documents=0,
                algorithm="greedy_agglomerative_complete_linkage",
                threshold_used=self.compatibility_config.compatibility_threshold,
            )

        # Sort profiles by document_id for deterministic processing
        sorted_profiles = sorted(profiles, key=lambda p: p.document_id)

        # Check for duplicate document IDs
        doc_ids = [p.document_id for p in sorted_profiles]
        if len(doc_ids) != len(set(doc_ids)):
            duplicate_ids = [doc_id for doc_id in doc_ids if doc_ids.count(doc_id) > 1]
            raise ValueError(f"Duplicate document IDs: {set(duplicate_ids)}")

        # Create a mapping for quick profile lookup
        profiles_by_id = {p.document_id: p for p in sorted_profiles}

        # Initialize: one singleton cluster per profile
        clusters: list[_InternalCluster] = []
        for profile in sorted_profiles:
            cluster = _InternalCluster(
                document_ids=[profile.document_id],
                document_filenames=[profile.filename],
                profiles_by_id=profiles_by_id,
            )
            clusters.append(cluster)

        # Greedy agglomerative clustering
        threshold = self.compatibility_config.compatibility_threshold
        merge_order = 0

        while len(clusters) > 1:
            # Find the pair of clusters with the highest minimum cross-cluster score
            best_pair = None
            best_min_score = -1.0

            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    cluster_i = clusters[i]
                    cluster_j = clusters[j]

                    # Compute minimum pairwise score between cluster_i and cluster_j
                    min_score = self._compute_inter_cluster_min_score(
                        cluster_i, cluster_j, profiles_by_id
                    )

                    # Tie-break deterministically using cluster identifiers
                    if min_score > best_min_score or (
                        min_score == best_min_score
                        and best_pair is not None
                        and self._is_lexicographically_smaller(
                            (i, j), best_pair, clusters
                        )
                    ):
                        best_min_score = min_score
                        best_pair = (i, j)

            # If no pair meets threshold, stop
            if best_pair is None or best_min_score < threshold:
                break

            # Merge the best pair
            i, j = best_pair
            cluster_i = clusters[i]
            cluster_j = clusters[j]

            # Record evidence for each merge
            for doc_a_id in cluster_i.document_ids:
                for doc_b_id in cluster_j.document_ids:
                    if doc_a_id < doc_b_id:
                        profile_a = profiles_by_id[doc_a_id]
                        profile_b = profiles_by_id[doc_b_id]
                        compat_result = self.scorer.compare(profile_a, profile_b)

                        evidence = {
                            "document_a_id": doc_a_id,
                            "document_b_id": doc_b_id,
                            "document_a_filename": profile_a.filename,
                            "document_b_filename": profile_b.filename,
                            "compatibility_score": compat_result.score,
                            "merge_order": merge_order,
                            "inter_cluster_min_score": best_min_score,
                        }
                        cluster_i.merge_evidence.append(evidence)

            # Merge cluster_j into cluster_i (keep lower index)
            cluster_i.document_ids.extend(cluster_j.document_ids)
            cluster_i.document_filenames.extend(cluster_j.document_filenames)
            cluster_i.merge_evidence.extend(cluster_j.merge_evidence)

            # Remove cluster_j (higher index)
            clusters.pop(j)
            merge_order += 1

        # Convert internal clusters to final FamilyCluster objects
        # and assign deterministic family IDs

        # Calculate confidence and pairwise scores for each cluster
        final_clusters_data = []
        for internal_cluster in clusters:
            pairwise_scores = self._compute_all_pairwise_scores(
                internal_cluster, profiles_by_id
            )
            confidence = self._calculate_cluster_confidence(
                internal_cluster, pairwise_scores, profiles_by_id
            )

            pairwise_score_mean = (
                sum(pairwise_scores) / len(pairwise_scores)
                if pairwise_scores
                else 1.0
            )
            pairwise_score_min = (
                min(pairwise_scores) if pairwise_scores else 1.0
            )

            final_clusters_data.append(
                {
                    "document_ids": internal_cluster.document_ids,
                    "document_filenames": internal_cluster.document_filenames,
                    "confidence": confidence,
                    "cluster_size": len(internal_cluster.document_ids),
                    "pairwise_scores": pairwise_scores,
                    "pairwise_score_mean": pairwise_score_mean,
                    "pairwise_score_min": pairwise_score_min,
                    "merge_evidence": internal_cluster.merge_evidence,
                }
            )

        # Sort clusters deterministically: by size descending, then by first doc_id ascending
        final_clusters_data.sort(
            key=lambda c: (-c["cluster_size"], c["document_ids"][0])
        )

        # Assign deterministic family IDs
        final_clusters = []
        for idx, cluster_data in enumerate(final_clusters_data):
            family_id = f"family_{idx + 1:03d}"  # family_001, family_002, ...
            family_cluster = FamilyCluster(
                family_id=family_id,
                document_ids=cluster_data["document_ids"],
                document_filenames=cluster_data["document_filenames"],
                confidence=cluster_data["confidence"],
                cluster_size=cluster_data["cluster_size"],
                pairwise_scores=cluster_data["pairwise_scores"],
                pairwise_score_mean=cluster_data["pairwise_score_mean"],
                pairwise_score_min=cluster_data["pairwise_score_min"],
                merge_evidence=cluster_data["merge_evidence"],
            )
            final_clusters.append(family_cluster)

        return ClusteringResult(
            clusters=final_clusters,
            num_clusters=len(final_clusters),
            num_documents=sum(c.cluster_size for c in final_clusters),
            algorithm="greedy_agglomerative_complete_linkage",
            threshold_used=threshold,
        )

    def _compute_inter_cluster_min_score(
        self, cluster_a: _InternalCluster, cluster_b: _InternalCluster, profiles_by_id: dict
    ) -> float:
        """Compute the minimum pairwise compatibility score between two clusters.

        Returns the MINIMUM compatibility score across all (doc_a, doc_b) pairs
        where doc_a is in cluster_a and doc_b is in cluster_b.
        """
        min_score = 1.0
        found_any = False

        for doc_a_id in cluster_a.document_ids:
            for doc_b_id in cluster_b.document_ids:
                profile_a = profiles_by_id[doc_a_id]
                profile_b = profiles_by_id[doc_b_id]

                result = self.scorer.compare(profile_a, profile_b)
                min_score = min(min_score, result.score)
                found_any = True

        return min_score if found_any else 0.0

    def _compute_all_pairwise_scores(
        self, cluster: _InternalCluster, profiles_by_id: dict
    ) -> list[float]:
        """Compute all pairwise compatibility scores within a cluster."""
        scores = []

        doc_ids = sorted(cluster.document_ids)  # deterministic order
        for i in range(len(doc_ids)):
            for j in range(i + 1, len(doc_ids)):
                doc_a_id = doc_ids[i]
                doc_b_id = doc_ids[j]

                profile_a = profiles_by_id[doc_a_id]
                profile_b = profiles_by_id[doc_b_id]

                result = self.scorer.compare(profile_a, profile_b)
                scores.append(result.score)

        return sorted(scores)  # return sorted for deterministic output

    def _calculate_cluster_confidence(
        self,
        cluster: _InternalCluster,
        pairwise_scores: list[float],
        profiles_by_id: dict,
    ) -> float:
        """Calculate confidence for a cluster.

        For singletons: profile-based completeness.
        For multi-document: 0.4 * min + 0.6 * mean of pairwise scores.
        """
        if cluster.cluster_size == 1:
            # Singleton: use profile-based completeness
            profile = profiles_by_id[cluster.document_ids[0]]
            return self._calculate_profile_completeness(profile)

        # Multi-document: aggregate pairwise scores
        if not pairwise_scores:
            return 1.0

        pairwise_score_min = min(pairwise_scores)
        pairwise_score_mean = sum(pairwise_scores) / len(pairwise_scores)

        confidence = 0.4 * pairwise_score_min + 0.6 * pairwise_score_mean
        return max(0.0, min(1.0, confidence))

    def _calculate_profile_completeness(self, profile: DocumentProfile) -> float:
        """Calculate profile completeness for singleton confidence.

        Mirrors CompatibilityScorer._calculate_profile_completeness() from Milestone 3.
        """
        completeness = 0.0

        if profile.structural.total_blocks > 0:
            completeness += 0.2
        if profile.structural.heading_count > 0:
            completeness += 0.2
        if len(profile.sections) > 0:
            completeness += 0.2
        if profile.content.unique_words_count > 0:
            completeness += 0.2
        if profile.structural.table_count > 0 or bool(
            profile.structural.table_dimensions
        ):
            completeness += 0.2

        return max(0.0, min(1.0, completeness))

    def _is_lexicographically_smaller(
        self, pair1: tuple[int, int], pair2: tuple[int, int], clusters: list
    ) -> bool:
        """Determine if pair1 is lexicographically smaller than pair2 based on cluster identifiers.

        Uses the first document_id in each cluster for comparison.
        """
        i1, j1 = pair1
        i2, j2 = pair2

        first_ids_1 = (clusters[min(i1, j1)].document_ids[0], clusters[max(i1, j1)].document_ids[0])
        first_ids_2 = (clusters[min(i2, j2)].document_ids[0], clusters[max(i2, j2)].document_ids[0])

        return first_ids_1 < first_ids_2


class _InternalCluster:
    """Internal representation of a cluster during agglomerative clustering."""

    def __init__(self, document_ids: list[str], document_filenames: list[str], profiles_by_id: dict):
        self.document_ids = document_ids
        self.document_filenames = document_filenames
        self.profiles_by_id = profiles_by_id
        self.merge_evidence: list[dict] = []

    @property
    def cluster_size(self) -> int:
        return len(self.document_ids)
