"""Unit tests for pipeline graph assembly module.

Tests verify the structural correctness of the graph topology:
- PATH_MAPS coverage
- NODES registry
- Valid edge targets
- Entry point configuration
"""

import pytest

from src.pipeline.graph import ENTRY_POINT, NODES, PATH_MAPS


# --- Expected node names ---

EXPECTED_NODES = {
    "ingest",
    "extract_text",
    "classify_document",
    "chunk",
    "embed",
    "extract_claims",
    "match_rules",
    "match_rules_against_sources",
    "merge_findings",
    "score_confidence",
    "route_to_queue",
    "human_review",
    "finalize",
}

# Valid terminal targets (not actual nodes but graph terminators)
TERMINAL_TARGETS = {"__end__", "__failed__"}


class TestPathMaps:
    """Tests for the PATH_MAPS constant."""

    def test_path_maps_contains_all_13_nodes(self):
        """PATH_MAPS has an entry for every node in the pipeline."""
        assert set(PATH_MAPS.keys()) == EXPECTED_NODES

    def test_path_maps_has_exactly_13_entries(self):
        """PATH_MAPS has exactly 13 source node entries."""
        assert len(PATH_MAPS) == 13

    def test_all_path_map_targets_are_valid(self):
        """Every target in every path map is either a known node or a terminal."""
        valid_targets = EXPECTED_NODES | TERMINAL_TARGETS
        for source_node, decisions in PATH_MAPS.items():
            for decision, target in decisions.items():
                assert target in valid_targets, (
                    f"PATH_MAPS['{source_node}']['{decision}'] = '{target}' "
                    f"is not a valid node or terminal target"
                )

    def test_ingest_path_map(self):
        """Ingest has next → extract_text, escalate → route_to_queue."""
        assert PATH_MAPS["ingest"] == {
            "next": "extract_text",
            "escalate": "route_to_queue",
        }

    def test_extract_text_path_map(self):
        """Extract text supports next, retry, and escalate."""
        assert PATH_MAPS["extract_text"] == {
            "next": "classify_document",
            "retry": "extract_text",
            "escalate": "route_to_queue",
        }

    def test_classify_document_path_map(self):
        """Classify document supports next, retry, and escalate."""
        assert PATH_MAPS["classify_document"] == {
            "next": "chunk",
            "escalate": "route_to_queue",
            "retry": "classify_document",
        }

    def test_chunk_path_map(self):
        """Chunk has next → embed and escalate → route_to_queue."""
        assert PATH_MAPS["chunk"] == {
            "next": "embed",
            "escalate": "route_to_queue",
        }

    def test_finalize_path_map_terminates(self):
        """Finalize's 'end' decision targets __end__ (graph termination)."""
        assert PATH_MAPS["finalize"]["end"] == "__end__"

    def test_retry_targets_point_to_self(self):
        """Nodes with retry edges point back to themselves."""
        nodes_with_retry = [
            node for node, paths in PATH_MAPS.items() if "retry" in paths
        ]
        for node in nodes_with_retry:
            assert PATH_MAPS[node]["retry"] == node, (
                f"Node '{node}' retry should point to itself, "
                f"got '{PATH_MAPS[node]['retry']}'"
            )


class TestNodes:
    """Tests for the NODES registry."""

    def test_nodes_has_exactly_13_entries(self):
        """NODES dict has exactly 13 node function entries."""
        assert len(NODES) == 13

    def test_nodes_contains_all_expected_names(self):
        """NODES contains all expected pipeline node names."""
        assert set(NODES.keys()) == EXPECTED_NODES

    def test_all_node_values_are_callable(self):
        """All entries in NODES are callable (functions)."""
        for node_name, node_fn in NODES.items():
            assert callable(node_fn), (
                f"NODES['{node_name}'] is not callable"
            )

    def test_nodes_keys_match_path_maps_keys(self):
        """NODES keys are identical to PATH_MAPS keys."""
        assert set(NODES.keys()) == set(PATH_MAPS.keys())


class TestEntryPoint:
    """Tests for graph entry point configuration."""

    def test_entry_point_is_ingest(self):
        """The graph entry point is set to 'ingest'."""
        assert ENTRY_POINT == "ingest"

    def test_entry_point_exists_in_nodes(self):
        """The entry point is a valid node in the NODES registry."""
        assert ENTRY_POINT in NODES


class TestGraphTopology:
    """Tests for overall graph topology correctness."""

    def test_nominal_path_is_reachable(self):
        """The nominal (happy path) traversal visits all 11 nodes in order.

        Starting from ingest, following 'next' decisions reaches finalize.
        """
        nominal_order = [
            "ingest",
            "extract_text",
            "classify_document",
            "chunk",
            "embed",
            "extract_claims",
            "match_rules",
            "match_rules_against_sources",
            "merge_findings",
            "score_confidence",
            "route_to_queue",
        ]
        for i in range(len(nominal_order) - 1):
            source = nominal_order[i]
            assert "next" in PATH_MAPS[source], (
                f"Node '{source}' has no 'next' decision in path map"
            )
            assert PATH_MAPS[source]["next"] == nominal_order[i + 1], (
                f"Expected '{source}' next → '{nominal_order[i + 1]}', "
                f"got '{PATH_MAPS[source]['next']}'"
            )

    def test_route_to_queue_escalate_goes_to_human_review(self):
        """route_to_queue escalation routes to human_review."""
        assert PATH_MAPS["route_to_queue"]["escalate"] == "human_review"

    def test_human_review_finalize_goes_to_finalize(self):
        """human_review 'finalize' decision routes to finalize node."""
        assert PATH_MAPS["human_review"]["finalize"] == "finalize"

    def test_finalize_end_terminates_graph(self):
        """finalize 'end' decision terminates the graph."""
        assert PATH_MAPS["finalize"]["end"] == "__end__"

    def test_all_escalation_targets_are_valid(self):
        """All escalation edges route to route_to_queue, human_review, or __end__."""
        valid_escalation_targets = {"route_to_queue", "human_review", "__end__"}
        for source, paths in PATH_MAPS.items():
            if "escalate" in paths:
                assert paths["escalate"] in valid_escalation_targets, (
                    f"Node '{source}' escalation target "
                    f"'{paths['escalate']}' is not valid"
                )
