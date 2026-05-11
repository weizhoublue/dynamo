# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import logging
import os
from typing import Any

from vllm.config import VllmConfig
from vllm.v1.engine.async_llm import AsyncLLM

logger = logging.getLogger(__name__)

DYNAMO_KV_EVENT_BLOCK_SIZE_KEY = "dynamo_kv_event_block_size"
DYNAMO_KV_EVENT_BLOCK_SIZE_ENV = "DYN_VLLM_KV_EVENT_BLOCK_SIZE"
MAIN_ATTENTION_KV_CACHE_KINDS = {
    "full_attention",
    "mla_attention",
    "sink_full_attention",
}


def get_env_kv_event_block_size() -> int | None:
    """Return the optional KV event block size override from the environment."""
    raw_value = os.environ.get(DYNAMO_KV_EVENT_BLOCK_SIZE_ENV)
    if raw_value is None:
        return None

    try:
        block_size = int(raw_value)
    except ValueError as e:
        raise ValueError(
            f"{DYNAMO_KV_EVENT_BLOCK_SIZE_ENV} must be a positive integer, "
            f"got: {raw_value}"
        ) from e

    if block_size <= 0:
        raise ValueError(
            f"{DYNAMO_KV_EVENT_BLOCK_SIZE_ENV} must be a positive integer, "
            f"got: {raw_value}"
        )
    return block_size


def get_configured_kv_event_block_size(vllm_config: VllmConfig) -> int:
    """Return the configured KV event block size, falling back to vLLM's cache block size."""
    env_block_size = get_env_kv_event_block_size()
    if env_block_size is not None:
        return env_block_size

    additional_config = vllm_config.additional_config or {}
    return additional_config.get(
        DYNAMO_KV_EVENT_BLOCK_SIZE_KEY,
        vllm_config.cache_config.block_size,
    )


def select_main_attention_block_size(
    group_metadata: list[dict[str, Any]],
    fallback_block_size: int,
) -> int:
    """Select the main-attention KV block size from engine cache-group metadata."""
    if not group_metadata:
        return fallback_block_size

    for group in group_metadata:
        if group.get("kind") in MAIN_ATTENTION_KV_CACHE_KINDS:
            return group.get("block_size", fallback_block_size)

    return fallback_block_size


async def configure_kv_event_block_size(
    engine: AsyncLLM,
    vllm_config: VllmConfig,
) -> int:
    """Fetch engine cache-group metadata and cache the KV event block size on vLLM config."""
    env_block_size = get_env_kv_event_block_size()
    if env_block_size is not None:
        kv_event_block_size = env_block_size
        logger.info(
            "Using KV event block size from %s: %s",
            DYNAMO_KV_EVENT_BLOCK_SIZE_ENV,
            kv_event_block_size,
        )
    else:
        kv_event_block_size = await get_engine_kv_event_block_size(engine, vllm_config)

    if vllm_config.additional_config is None:
        vllm_config.additional_config = {}
    vllm_config.additional_config[DYNAMO_KV_EVENT_BLOCK_SIZE_KEY] = kv_event_block_size
    return kv_event_block_size


async def get_engine_kv_event_block_size(
    engine: AsyncLLM,
    vllm_config: VllmConfig,
) -> int:
    """Fetch engine cache-group metadata and return the KV event block size."""
    fallback_block_size = vllm_config.cache_config.block_size
    try:
        group_metadata = await engine.engine_core.call_utility_async(
            "get_kv_cache_group_metadata"
        )
    except Exception as e:
        logger.warning(
            "Failed to fetch KV cache group metadata; falling back to "
            "vLLM cache_config.block_size. This may be unsafe for hybrid KV "
            "cache layouts such as Mamba; set %s to the vLLM KV event block "
            "size if events are dropped by the router: %s",
            DYNAMO_KV_EVENT_BLOCK_SIZE_ENV,
            e,
        )
        return fallback_block_size
    else:
        return select_main_attention_block_size(
            group_metadata,
            fallback_block_size,
        )
