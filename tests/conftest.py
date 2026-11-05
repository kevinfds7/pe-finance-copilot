import os
import tempfile

os.environ.setdefault("PE_COPILOT_DATA_DIR", tempfile.mkdtemp(prefix="pe_test_"))

import pytest  # noqa: E402

from pe_copilot import pipeline  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def built_db():
    return pipeline.build()
