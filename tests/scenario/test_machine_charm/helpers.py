# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import MagicMock


def set_run_out(mock_run, returncode: int = 0, stdout: str = "", stderr: str = ""):
    mock_stdout = MagicMock()
    mock_stdout.configure_mock(
        **{
            "returncode": returncode,
            "stdout.decode.return_value": stdout,
            "stderr.decode.return_value": stderr,
        }
    )
    mock_run.return_value = mock_stdout
