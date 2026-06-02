from sandbox.absolute_value import absolute_value


def test_absolute_value_negative():
    assert absolute_value(-5) == 5


def test_absolute_value_positive():
    assert absolute_value(7) == 7


def test_absolute_value_zero():
    assert absolute_value(0) == 0
