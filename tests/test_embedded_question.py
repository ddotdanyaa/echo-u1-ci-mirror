# factory-backlog-id: C07-echo.s1

def test_embedded_question():
    from echo_sync.classifier import _clause_question
    res = _clause_question("Но ведь причина есть, мы же договорились.", None, {}, False)
    assert res is not None
    assert res.by_trigger is True
