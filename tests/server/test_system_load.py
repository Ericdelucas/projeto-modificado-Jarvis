"""HUD CPU/GPU readout without a real GPU."""

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from openjarvis.server.routes import _gpu_load


def test_no_nvidia_smi_means_no_gpu():
    with patch("shutil.which", return_value=None):
        assert _gpu_load() is None


def test_parses_first_gpu_and_survives_failures():
    out = "NVIDIA GeForce RTX 4050 Laptop GPU, 37\nOther GPU, 1\n"
    with (
        patch("shutil.which", return_value="/usr/bin/nvidia-smi"),
        patch("subprocess.run", return_value=SimpleNamespace(stdout=out)),
    ):
        assert _gpu_load() == {
            "name": "NVIDIA GeForce RTX 4050 Laptop GPU",
            "percent": 37.0,
        }
    with (
        patch("shutil.which", return_value="/usr/bin/nvidia-smi"),
        patch("subprocess.run", side_effect=subprocess.TimeoutExpired("smi", 2)),
    ):
        assert _gpu_load() is None
