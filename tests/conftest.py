import pytest

from app import security


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    # limit zapytań liczy w pamięci procesu - każdy test zaczyna od zera
    security._hits.clear()
