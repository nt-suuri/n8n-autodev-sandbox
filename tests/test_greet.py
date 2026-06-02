from sandbox.greet import greet


def test_greet_returns_greeting():
    assert greet("Daisy") == "Hello, Daisy!"
