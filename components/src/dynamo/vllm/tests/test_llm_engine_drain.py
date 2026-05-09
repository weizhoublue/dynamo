# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib
import sys
import types
from enum import Enum
from pathlib import Path

import pytest


def _install_import_stubs(monkeypatch):
    src_path = Path(__file__).resolve().parents[3]
    repo_path = src_path.parents[1]
    bindings_path = repo_path / "lib" / "bindings" / "python" / "src"
    monkeypatch.syspath_prepend(str(src_path))
    monkeypatch.syspath_prepend(str(bindings_path))

    core = types.ModuleType("dynamo._core")
    core.Context = object
    core.backend = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "dynamo._core", core)

    llm = types.ModuleType("dynamo.llm")

    class ModelInput(Enum):
        Tokens = "tokens"

    llm.ModelInput = ModelInput
    monkeypatch.setitem(sys.modules, "dynamo.llm", llm)

    backend_engine = types.ModuleType("dynamo.common.backend.engine")
    backend_engine.EngineConfig = object
    backend_engine.GenerateChunk = dict
    backend_engine.GenerateRequest = dict
    backend_engine.LLMEngine = object
    monkeypatch.setitem(sys.modules, "dynamo.common.backend.engine", backend_engine)

    backend_worker = types.ModuleType("dynamo.common.backend.worker")

    class WorkerConfig:
        @classmethod
        def from_runtime_config(cls, *args, **kwargs):
            return cls()

    backend_worker.WorkerConfig = WorkerConfig
    monkeypatch.setitem(sys.modules, "dynamo.common.backend.worker", backend_worker)

    constants = types.ModuleType("dynamo.vllm.constants")

    class DisaggregationMode(Enum):
        AGGREGATED = "agg"
        PREFILL = "prefill"
        DECODE = "decode"

    constants.DisaggregationMode = DisaggregationMode
    monkeypatch.setitem(sys.modules, "dynamo.vllm.constants", constants)

    vllm_inputs = types.ModuleType("vllm.inputs")
    vllm_inputs.TokensPrompt = object
    monkeypatch.setitem(sys.modules, "vllm.inputs", vllm_inputs)

    usage_lib = types.ModuleType("vllm.usage.usage_lib")
    usage_lib.UsageContext = types.SimpleNamespace(OPENAI_API_SERVER="openai")
    monkeypatch.setitem(sys.modules, "vllm.usage.usage_lib", usage_lib)

    async_llm = types.ModuleType("vllm.v1.engine.async_llm")
    async_llm.AsyncLLM = object
    monkeypatch.setitem(sys.modules, "vllm.v1.engine.async_llm", async_llm)

    vllm_args = types.ModuleType("dynamo.vllm.args")
    vllm_args.parse_args = lambda argv=None: None
    monkeypatch.setitem(sys.modules, "dynamo.vllm.args", vllm_args)

    handlers = types.ModuleType("dynamo.vllm.handlers")
    handlers.build_sampling_params = lambda request, defaults, model_max_len: defaults
    monkeypatch.setitem(sys.modules, "dynamo.vllm.handlers", handlers)


@pytest.fixture
def llm_engine_module(monkeypatch):
    _install_import_stubs(monkeypatch)
    sys.modules.pop("dynamo.vllm.llm_engine", None)
    return importlib.import_module("dynamo.vllm.llm_engine")


class _PauseableClient:
    def __init__(self):
        self.calls = []

    async def pause_generation(self, **kwargs):
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_drain_waits_for_prefill_generation(llm_engine_module):
    engine = llm_engine_module.VllmLLMEngine(
        object(), llm_engine_module.DisaggregationMode.PREFILL
    )
    engine.engine_client = _PauseableClient()

    await engine.drain()

    assert engine.engine_client.calls == [{"mode": "wait", "clear_cache": False}]


@pytest.mark.asyncio
async def test_drain_skips_non_prefill_generation(llm_engine_module):
    engine = llm_engine_module.VllmLLMEngine(
        object(), llm_engine_module.DisaggregationMode.DECODE
    )
    engine.engine_client = _PauseableClient()

    await engine.drain()

    assert engine.engine_client.calls == []
