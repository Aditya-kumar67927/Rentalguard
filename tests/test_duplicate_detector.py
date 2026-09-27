import numpy as np
import pytest

from app.services.duplicate_detector import DuplicateDetector, MinHashLSH, shingles
from app.utils.text import normalize_text

TEXT = ("Sea facing fully furnished 2 BHK apartment on a high floor with a large balcony, Italian marble "
        "flooring, modular kitchen with chimney and hob, two air conditioners and a covered car park.")


def test_normalisation_pipeline():
    assert normalize_text("  Hello,   WORLD!! 2-BHK\n") == "hello world 2 bhk"


def test_exact_duplicate(duplicate_detector, reference_frame):
    text = reference_frame.description.iloc[3]
    matches = duplicate_detector.similar(text)
    assert matches[0]["id"] == reference_frame.listing_id.iloc[3]
    assert matches[0]["similarity"] == pytest.approx(1.0, abs=1e-3)


def test_exclude_self(duplicate_detector, reference_frame):
    lid = reference_frame.listing_id.iloc[3]
    ids = [m["id"] for m in duplicate_detector.similar(reference_frame.description.iloc[3], exclude_id=lid)]
    assert lid not in ids


def test_near_duplicate_with_conflicting_details(duplicate_detector):
    duplicate_detector.add(TEXT, {"id": "L1", "rent": 95000.0, "bhk": 2, "locality": "Bandra West",
                                  "locality_group": "bandra west", "zone": "South West Mumbai", "source": "user"})
    copy = TEXT.replace("a covered car park", "one covered car park")
    r = duplicate_detector.analyze({"description": copy, "rent": 22000, "_zone": "Navi Mumbai"})
    assert r["possible_duplicate"] is True
    assert r["max_similarity"] >= 0.9
    assert r["conflicting_duplicate"] is True
    assert len(r["conflicts"]) == 2      # price and zone


def test_consistent_repost_is_not_a_conflict(duplicate_detector):
    duplicate_detector.add(TEXT, {"id": "L1", "rent": 95000.0, "bhk": 2, "locality": "Bandra West",
                                  "locality_group": "bandra west", "zone": "South West Mumbai", "source": "user"})
    r = duplicate_detector.analyze({"description": TEXT, "rent": 95000, "_zone": "South West Mumbai"})
    assert r["possible_duplicate"] and not r["conflicting_duplicate"]


def test_unrelated_text_is_unique(duplicate_detector):
    r = duplicate_detector.analyze({"description": "Independent bungalow with private garden, a mango orchard and "
                                                   "a farm pond in a quiet village far away from the city."})
    assert r["level"] == "UNIQUE"
    assert r["possible_duplicate"] is False


@pytest.mark.parametrize("desc", [None, "", "too short text"])
def test_short_or_missing_description(duplicate_detector, desc):
    r = duplicate_detector.analyze({"description": desc})
    assert r["available"] is False and r["max_similarity"] == 0.0


def test_empty_detector_before_fit():
    assert DuplicateDetector().similar(TEXT) == []
    with pytest.raises(RuntimeError):
        DuplicateDetector().add(TEXT, {"id": "x"})


def test_add_is_idempotent(duplicate_detector):
    n = len(duplicate_detector)
    meta = {"id": "L9", "rent": 1.0, "bhk": 1, "locality": "x", "locality_group": "x", "zone": "x", "source": "user"}
    duplicate_detector.add(TEXT, meta)
    duplicate_detector.add(TEXT, meta)
    assert len(duplicate_detector) == n + 1


def test_minhash_estimates_jaccard():
    lsh = MinHashLSH(num_perm=256, bands=64)
    a = shingles(normalize_text(TEXT))
    b = shingles(normalize_text(TEXT.replace("Italian marble", "vitrified tile")))
    true_j = len(a & b) / len(a | b)
    est = float(np.mean(lsh.signature(a) == lsh.signature(b)))
    assert abs(est - true_j) < 0.12


def test_lsh_recall_matches_bruteforce(duplicate_detector, reference_frame):
    """Every brute-force neighbour with cosine >= 0.9 must also be found through LSH candidates."""
    missed = found = 0
    for i in range(0, len(reference_frame), 9):
        text = reference_frame.description.iloc[i]
        brute = {j for j, s in duplicate_detector.similar_bruteforce(text, 5) if s >= 0.9}
        lsh = {duplicate_detector.id_to_pos[m["id"]] for m in duplicate_detector.similar(text, 5, min_similarity=0.9)}
        found += len(brute & lsh)
        missed += len(brute - lsh)
    assert found > 0
    assert missed / (found + missed) <= 0.1


def test_lsh_prunes_candidates(duplicate_detector, reference_frame):
    sig = duplicate_detector.lsh.signature(shingles(normalize_text(reference_frame.description.iloc[0])))
    assert len(duplicate_detector.lsh.candidates(sig)) < len(duplicate_detector)
