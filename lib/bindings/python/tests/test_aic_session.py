# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_AIC_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "dynamo" / "_internal" / "aic.py"
)
_AIC_SPEC = importlib.util.spec_from_file_location("dynamo._internal.aic", _AIC_PATH)
aic = importlib.util.module_from_spec(_AIC_SPEC)
assert _AIC_SPEC.loader is not None
_AIC_SPEC.loader.exec_module(aic)

pytestmark = [
    pytest.mark.gpu_0,
    pytest.mark.parallel,
    pytest.mark.pre_merge,
    pytest.mark.unit,
]


class _FakeConfig:
    class ModelConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs


class _FakeOp:
    _name = "fake_op"

    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    def query(self, *args, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._result


class _FakeModel:
    model_name = "fake-model"
    _nextn = 0

    def __init__(self, context_result=1.0, generation_result=1.0, query_exc=None):
        self.context_ops = [_FakeOp(context_result, query_exc)]
        self.generation_ops = [_FakeOp(generation_result, query_exc)]


def _fake_aic_modules(model=None, session_exc=None):
    def _create_session(**kwargs):
        if session_exc is not None:
            raise session_exc
        return SimpleNamespace(**kwargs)

    return {
        "config": _FakeConfig,
        "get_backend": lambda backend_name: backend_name,
        "InferenceSession": _create_session,
        "get_model": lambda **kwargs: model or _FakeModel(),
        "get_database": lambda **kwargs: object(),
        "get_supported_databases": lambda: {},
    }


def test_create_session_reports_aic_type_error_with_context(monkeypatch):
    monkeypatch.setattr(
        aic,
        "_load_aiconfigurator",
        lambda: _fake_aic_modules(session_exc=TypeError("unsupported operand")),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "AIC perf model setup failed.*system='b200_sxm'.*backend='vllm'.*"
            "version='0.19.0'.*model_path='MiniMax'.*tp_size=8.*"
            "moe_tp_size=1.*moe_ep_size=8.*attention_dp_size=1"
        ),
    ):
        aic.create_session(
            "vllm",
            "b200_sxm",
            "MiniMax",
            8,
            "0.19.0",
            moe_tp_size=1,
            moe_ep_size=8,
            attention_dp_size=1,
        )


def test_predict_prefill_reports_none_query_result(monkeypatch):
    monkeypatch.setattr(
        aic,
        "_load_aiconfigurator",
        lambda: _fake_aic_modules(model=_FakeModel(context_result=None)),
    )
    session = aic.create_session("vllm", "b200_sxm", "MiniMax", 8, "0.19.0")

    with pytest.raises(
        RuntimeError,
        match="AIC perf model query returned no latency.*phase='prefill'",
    ):
        session.predict_prefill(batch_size=1, effective_isl=51200, prefix=0)


def test_predict_decode_reports_query_type_error(monkeypatch):
    monkeypatch.setattr(
        aic,
        "_load_aiconfigurator",
        lambda: _fake_aic_modules(
            model=_FakeModel(query_exc=TypeError("unsupported operand"))
        ),
    )
    session = aic.create_session("vllm", "b200_sxm", "MiniMax", 8, "0.19.0")

    with pytest.raises(
        RuntimeError,
        match="AIC perf model query failed.*phase='decode'",
    ):
        session.predict_decode(batch_size=1, isl=51200, osl=2)
