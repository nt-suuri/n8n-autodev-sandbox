import pytest

from sandbox.division import division


def test_division():
    assert division(10, 4) == 2.5


def test_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        division(10, 0)
