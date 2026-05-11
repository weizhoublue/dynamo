# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _install_fake_vllm_modules() -> dict[str, ModuleType | None]:
    vllm_module = ModuleType("vllm")
    config_module = ModuleType("vllm.config")
    v1_module = ModuleType("vllm.v1")
    engine_module = ModuleType("vllm.v1.engine")
    async_llm_module = ModuleType("vllm.v1.engine.async_llm")

    config_module.VllmConfig = object
    async_llm_module.AsyncLLM = object

    modules = {
        "vllm": vllm_module,
        "vllm.config": config_module,
        "vllm.v1": v1_module,
        "vllm.v1.engine": engine_module,
        "vllm.v1.engine.async_llm": async_llm_module,
    }
    previous_modules = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    return previous_modules


def _restore_modules(previous_modules: dict[str, ModuleType | None]) -> None:
    for name, module in previous_modules.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


_previous_modules = _install_fake_vllm_modules()
try:
    from dynamo.vllm.cache_info import configure_kv_event_block_size  # noqa: E402
finally:
    _restore_modules(_previous_modules)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.vllm,
    pytest.mark.gpu_1,
    pytest.mark.pre_merge,
]


def _make_vllm_config(block_size: int = 16) -> SimpleNamespace:
    return SimpleNamespace(
        cache_config=SimpleNamespace(block_size=block_size),
        additional_config=None,
    )


def _make_engine(group_metadata: list[dict]) -> SimpleNamespace:
    call_utility_async = AsyncMock(return_value=group_metadata)
    return SimpleNamespace(
        engine_core=SimpleNamespace(call_utility_async=call_utility_async)
    )


@pytest.mark.asyncio
async def test_env_override_takes_precedence_over_metadata(monkeypatch):
    monkeypatch.setenv("DYN_VLLM_KV_EVENT_BLOCK_SIZE", "2096")
    vllm_config = _make_vllm_config()
    engine = _make_engine([{"kind": "full_attention", "block_size": 16}])

    block_size = await configure_kv_event_block_size(engine, vllm_config)

    assert block_size == 2096
    assert vllm_config.additional_config["dynamo_kv_event_block_size"] == 2096
    engine.engine_core.call_utility_async.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("override", ["0", "-1", "not-an-int"])
async def test_env_override_must_be_positive_integer(monkeypatch, override):
    monkeypatch.setenv("DYN_VLLM_KV_EVENT_BLOCK_SIZE", override)
    vllm_config = _make_vllm_config()
    engine = _make_engine([{"kind": "full_attention", "block_size": 16}])

    with pytest.raises(ValueError, match="DYN_VLLM_KV_EVENT_BLOCK_SIZE"):
        await configure_kv_event_block_size(engine, vllm_config)

    engine.engine_core.call_utility_async.assert_not_called()
