import pytest


@pytest.mark.hardware
def test_i2c_with_device() -> None:
    """
    @brief Example hardware test.
    @details Runs only when -m hardware is used.
    """
    assert True
