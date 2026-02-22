"""Pytest configuration and fixtures.

Optional dataset environment variables for integration tests:
    REALTALK_PATH      – path to the REALTALK dyad directory
    KAGGLE_WA_CSV      – path to the Kaggle WhatsApp export CSV
    CANDOR_SESSION_JSON – path to the CANDOR session JSON file
"""

import pytest


def pytest_addoption(parser):
    """Add --integration CLI option."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests that make real API calls",
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless --integration is passed."""
    if config.getoption("--integration"):
        # --integration given in CLI: do not skip integration tests
        return

    skip_integration = pytest.mark.skip(
        reason="need --integration option to run"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


def converted_fixture(dataset: str, raw_path: str | None, **kwargs) -> str:
    """Return the raw dataset path if it exists, otherwise skip the test.

    Used by dataset integration tests to skip gracefully when the raw data
    has not been downloaded locally.

    Args:
        dataset: Human-readable dataset name (e.g. "realtalk").
        raw_path: Value of the env-var pointing to the raw data, or None.
        **kwargs: Ignored (reserved for future use).

    Returns:
        The ``raw_path`` string if the path exists.

    Raises:
        pytest.skip.Exception: If ``raw_path`` is None or the path does not exist.
    """
    import os
    if raw_path is None or not os.path.exists(raw_path):
        env_var = dataset.upper().replace("-", "_") + "_PATH"
        pytest.skip(
            f"{dataset} raw data not found — download and set {env_var}"
        )
    return raw_path
