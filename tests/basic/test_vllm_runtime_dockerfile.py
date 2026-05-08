# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path


def test_cuda13_vllm_runtime_installs_matching_cupy() -> None:
    dockerfile = Path("container/templates/vllm_runtime.Dockerfile").read_text()

    cuda13_branch = dockerfile.split('if [ "${CUDA_VERSION%%.*}" = "13" ]; then', 1)[1]
    cuda13_branch = cuda13_branch.split("fi", 1)[0]

    assert "uv pip uninstall -y cupy-cuda12x" in cuda13_branch
    assert "uv pip install cupy-cuda13x" in cuda13_branch
