import pytest

from decision_guide.catalog import load_catalog


@pytest.fixture(scope="session")
def catalog():
    return load_catalog()
