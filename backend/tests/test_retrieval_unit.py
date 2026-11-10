import numpy as np

from app.services.rag import NOT_FOUND_TEXT, build_user_prompt, extract_citations
from app.services.retrieval import Hit, bm25_scores, reciprocal_rank_fusion, tokenize
from app.services.vectors import from_bytes, normalise, to_bytes


def make_hit(text="some text", page=3, name="manual.pdf"):
    return Hit(1, "doc", name, page, 0, text, 0.1, None, None)


def test_tokenize_lowercases_and_splits():
    assert tokenize("Pump P-101, Section 4.2!") == ["pump", "p", "101", "section", "4", "2"]


def test_bm25_ranks_matching_document_first_and_zero_for_no_match():
    docs = [tokenize(t) for t in ["fire drill at gate four", "pump isolation procedure", "leave policy"]]
    scores = bm25_scores(tokenize("pump isolation"), docs)
    assert scores[1] > 0 and scores[0] == 0 and scores[2] == 0


def test_bm25_rare_words_count_more_than_common_words():
    docs = [tokenize(t) for t in ["the pump the valve", "the the the the", "the the lamp"]]
    scores = bm25_scores(tokenize("the pump"), docs)
    assert scores[0] > scores[1]


def test_bm25_empty_input():
    assert bm25_scores(["a"], []) == []


def test_rrf_rewards_items_ranked_well_in_both_lists():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 2, 9]])
    order = sorted(fused, key=fused.get, reverse=True)
    assert order[0] == 2 or order[0] == 3
    assert fused[2] > fused[1] and fused[2] > fused[9]


def test_vector_roundtrip_and_normalisation():
    data, dim = to_bytes([3.0, 4.0])
    assert dim == 2
    restored = from_bytes(data)
    assert np.allclose(restored, [0.6, 0.8], atol=1e-6)
    assert np.isclose(np.linalg.norm(normalise([10, 0, 0])), 1.0)
    assert to_bytes([0.0, 0.0])[1] == 2  # zero vector does not crash


def test_prompt_numbers_sources_and_includes_pages():
    prompt = build_user_prompt("What is X?", [make_hit("alpha"), make_hit("beta", page=None, name="n.txt")])
    assert "[1] (file: manual.pdf, page 3)" in prompt
    assert "[2] (file: n.txt)" in prompt
    assert "QUESTION: What is X?" in prompt


def test_extract_citations_valid_and_invalid():
    valid, invalid = extract_citations("Do A [1]. Do B [2, 3]. Also [9].", 3)
    assert valid == [1, 2, 3] and invalid == [9]


def test_extract_citations_none():
    assert extract_citations(NOT_FOUND_TEXT, 3) == ([], [])
