from sandbox.farewell import farewell


def test_farewell_returns_goodbye():
    assert farewell("Daisy") == "Goodbye, Daisy!"
