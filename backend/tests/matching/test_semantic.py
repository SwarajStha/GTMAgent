"""Unit tests for the semantic cosine scorer (pure, no ML deps)."""
from __future__ import annotations

import math

from app.matching.semantic import SemanticScorer, cosine_similarity


def test_cosine_identical_vectors_is_one() -> None:
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_cosine_orthogonal_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_opposite_is_negative_one() -> None:
    assert math.isclose(cosine_similarity([1.0, 0.0], [-1.0, 0.0]), -1.0)


def test_cosine_handles_degenerate_inputs() -> None:
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0  # length mismatch


def test_score_maps_high_cosine_near_one() -> None:
    # identical -> cosine 1.0 -> (1.0-0.05)/0.90 = 1.055 -> clipped to 1.0
    assert SemanticScorer().score([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_score_maps_orthogonal_to_zero() -> None:
    # cosine 0 -> (0-0.05)/0.90 < 0 -> clipped to 0.0
    assert SemanticScorer().score([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_score_is_in_unit_range() -> None:
    s = SemanticScorer().score([0.4, 0.5, 0.2], [0.3, 0.6, 0.1])
    assert 0.0 <= s <= 1.0
