import warnings

import pytest

warnings.filterwarnings("ignore", message=".*httpx2.*")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import use_data_dir  # noqa: E402
from app.database import session as S  # noqa: E402


@pytest.fixture()
def workspace(tmp_path):
    use_data_dir(tmp_path / "data", tmp_path / "models")
    S.reset_engine()
    yield tmp_path
    S.reset_engine()


@pytest.fixture()
def client(workspace):
    from app.main import app
    with TestClient(app) as c:
        yield c
