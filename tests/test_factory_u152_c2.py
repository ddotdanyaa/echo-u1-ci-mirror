# factory-backlog-id: U152#2
from echo_sync import reference_kb

def test_u152_c2_laws_base_article_parts():
    # The requirement is to connect to the law base (E91) and return the article verbatim in chunks.
    # We use a known article that should exist in the law base (e.g., Article 19 of the Tax Code).
    # The current implementation returns a single string or None, failing to chunk the output.
    res = reference_kb.lookup("статья 19 налогового кодекса")
    
    # The defect is that it should return a list of strings (chunks) for verbatim text,
    # but currently it returns a single string (or None).
    assert isinstance(res, list), f"Expected a list of chunks, got {type(res)}"
    assert len(res) > 1, "Expected multiple chunks for the article text"
    assert all(isinstance(chunk, str) for chunk in res), "All chunks must be strings"
