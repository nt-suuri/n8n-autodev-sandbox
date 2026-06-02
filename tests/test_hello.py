from sandbox.hello import hello


def test_hello_returns_hi():
    assert hello() == 'hi'
