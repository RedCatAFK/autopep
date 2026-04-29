from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from autopep_agent import biology_tools
from autopep_agent.db import (
    create_artifact,
    create_candidate,
    create_model_inference,
    complete_model_inference,
    insert_candidate_scores,
    map_scoring_result_to_rows,
    update_candidate_fold_artifact,
)
from autopep_agent.run_context import (
    ToolRunContext,
    get_tool_run_context,
    set_tool_run_context,
)


# ---------------------------------------------------------------------------
# map_scoring_result_to_rows
# ---------------------------------------------------------------------------


def test_map_scoring_result_to_candidate_score_rows_ok() -> None:
    rows = map_scoring_result_to_rows(
        candidate_id="candidate-1",
        model_inference_id="inference-1",
        result={
            "status": "ok",
            "scores": {
                "dscript": {
                    "available": True,
                    "interaction_probability": 0.74,
                    "raw_score": 1.2,
                },
                "prodigy": {
                    "available": True,
                    "delta_g_kcal_per_mol": -7.4,
                    "kd_molar": 3.8e-6,
                },
            },
            "aggregate": {"available": True, "label": "likely_binder", "notes": []},
            "warnings": [],
            "errors": [],
        },
    )

    assert rows[0]["scorer"] == "dscript"
    assert rows[0]["status"] == "ok"
    assert rows[0]["value"] == 0.74
    assert rows[0]["unit"] == "probability"
    assert rows[0]["candidate_id"] == "candidate-1"
    assert rows[0]["model_inference_id"] == "inference-1"

    assert rows[1]["scorer"] == "prodigy"
    assert rows[1]["status"] == "ok"
    assert rows[1]["value"] == -7.4
    assert rows[1]["unit"] == "kcal/mol"

    assert rows[2]["scorer"] == "protein_interaction_aggregate"
    assert rows[2]["status"] == "ok"
    assert rows[2]["label"] == "likely_binder"
    assert rows[2]["value"] is None
    assert rows[2]["unit"] is None


def test_map_scoring_result_to_candidate_score_rows_partial() -> None:
    rows = map_scoring_result_to_rows(
        candidate_id="candidate-7",
        model_inference_id="inference-7",
        result={
            "status": "partial",
            "scores": {
                "dscript": {"available": True, "interaction_probability": 0.31},
                "prodigy": {"available": False},
            },
            "aggregate": {"available": True, "label": "uncertain"},
            "warnings": ["prodigy unavailable"],
            "errors": [],
        },
    )

    assert rows[0]["scorer"] == "dscript"
    assert rows[0]["status"] == "partial"

    assert rows[1]["scorer"] == "prodigy"
    assert rows[1]["status"] == "unavailable"
    assert rows[1]["value"] is None

    assert rows[2]["scorer"] == "protein_interaction_aggregate"
    assert rows[2]["status"] == "partial"
    assert rows[2]["label"] == "uncertain"
    assert rows[2]["warnings_json"] == ["prodigy unavailable"]


def test_map_scoring_result_to_candidate_score_rows_failed() -> None:
    rows = map_scoring_result_to_rows(
        candidate_id="c1",
        model_inference_id="i1",
        result={
            "status": "failed",
            "scores": {
                "dscript": {"available": False},
                "prodigy": {"available": False},
            },
            "aggregate": {"available": False},
            "warnings": [],
            "errors": ["dscript timed out", "prodigy timed out"],
        },
    )

    # All three rows present, but each individual scorer is unavailable when
    # its `available` flag is False — even when the overall status is failed.
    assert rows[0]["scorer"] == "dscript"
    assert rows[0]["status"] == "unavailable"
    assert rows[1]["scorer"] == "prodigy"
    assert rows[1]["status"] == "unavailable"
    assert rows[2]["scorer"] == "protein_interaction_aggregate"
    assert rows[2]["status"] == "unavailable"
    assert rows[2]["errors_json"] == ["dscript timed out", "prodigy timed out"]


def test_map_scoring_result_to_candidate_score_rows_unavailable_dscript() -> None:
    rows = map_scoring_result_to_rows(
        candidate_id="c1",
        model_inference_id="i1",
        result={
            "status": "ok",
            "scores": {
                "dscript": {"available": False},
                "prodigy": {
                    "available": True,
                    "delta_g_kcal_per_mol": -3.0,
                    "kd_molar": 1e-3,
                },
            },
            "aggregate": {"available": True, "label": "likely_binder"},
            "warnings": [],
            "errors": [],
        },
    )

    # When dscript is unavailable but the overall run is "ok", the dscript row
    # still gets `status="unavailable"` per its individual flag, while the
    # prodigy and aggregate rows pick up the run-level "ok".
    assert rows[0]["status"] == "unavailable"
    assert rows[1]["status"] == "ok"
    assert rows[2]["status"] == "ok"


# ---------------------------------------------------------------------------
# DB helpers — signature + SQL parameter shape
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Async-context-manager cursor that records executes and serves canned rows."""

    def __init__(
        self,
        returning: list[Any] | None = None,
        *,
        rowcounts: list[int] | None = None,
    ) -> None:
        self.executes: list[tuple[str, tuple[Any, ...]]] = []
        self._returning = list(returning or [])
        self._rowcounts = list(rowcounts or [])
        self.rowcount = 1

    async def __aenter__(self) -> "_FakeCursor":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executes.append((sql, tuple(params or ())))
        if self._rowcounts:
            self.rowcount = self._rowcounts.pop(0)

    async def fetchone(self) -> Any:
        if not self._returning:
            return None
        return self._returning.pop(0)


class _FakeConn:
    """Async-context-manager fake psycopg connection that returns one cursor."""

    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


def _patch_psycopg_connect(
    monkeypatch: pytest.MonkeyPatch,
    cursor: _FakeCursor,
) -> None:
    import psycopg

    fake_conn = _FakeConn(cursor)
    connect = AsyncMock(return_value=fake_conn)
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)


@pytest.mark.asyncio
async def test_create_model_inference_inserts_running_row_and_returns_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(returning=[("00000000-0000-0000-0000-000000000123",)])
    _patch_psycopg_connect(monkeypatch, cursor)

    inference_id = await create_model_inference(
        "postgres://x",
        workspace_id="w1",
        run_id="r1",
        model_name="proteina_complexa",
        request_json={"foo": "bar"},
        endpoint_url="https://proteina.example/run",
    )

    assert inference_id == "00000000-0000-0000-0000-000000000123"
    assert len(cursor.executes) == 1
    sql, params = cursor.executes[0]
    assert "insert into autopep_model_inference" in sql
    assert "running" in sql
    assert params[0] == "w1"
    assert params[1] == "r1"
    assert params[2] == "proteina_complexa"
    assert params[3] == "https://proteina.example/run"
    assert json.loads(params[4]) == {"foo": "bar"}


@pytest.mark.asyncio
async def test_complete_model_inference_updates_status_response_and_finished_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor()
    _patch_psycopg_connect(monkeypatch, cursor)

    await complete_model_inference(
        "postgres://x",
        inference_id="i1",
        status="completed",
        response_json={"raw": True},
        error_summary=None,
    )

    assert len(cursor.executes) == 1
    sql, params = cursor.executes[0]
    assert "update autopep_model_inference" in sql
    assert "finished_at" in sql
    assert "completed" in params
    assert json.loads([p for p in params if isinstance(p, str) and p.startswith("{")][0]) == {
        "raw": True,
    }
    assert "i1" in params


@pytest.mark.asyncio
async def test_complete_model_inference_records_error_summary_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor()
    _patch_psycopg_connect(monkeypatch, cursor)

    await complete_model_inference(
        "postgres://x",
        inference_id="i1",
        status="failed",
        response_json={},
        error_summary="boom",
    )

    sql, params = cursor.executes[0]
    assert "failed" in params
    assert "boom" in params


@pytest.mark.asyncio
async def test_create_artifact_inserts_with_r2_provider_and_returns_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(returning=[("00000000-0000-0000-0000-000000000abc",)])
    _patch_psycopg_connect(monkeypatch, cursor)

    artifact_id = await create_artifact(
        "postgres://x",
        workspace_id="w1",
        run_id="r1",
        kind="proteina_result",
        name="design-1.pdb",
        storage_key="projects/w1/runs/r1/proteina-result/design-1.pdb",
        content_type="chemical/x-pdb",
        size_bytes=1024,
        sha256="deadbeef",
    )

    assert artifact_id == "00000000-0000-0000-0000-000000000abc"
    sql, params = cursor.executes[0]
    assert "insert into autopep_artifact" in sql
    assert "r2" in sql or "r2" in params
    assert "w1" in params
    assert "r1" in params
    assert "proteina_result" in params
    assert "design-1.pdb" in params
    assert "deadbeef" in params


@pytest.mark.asyncio
async def test_create_candidate_inserts_with_source_and_returns_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(returning=[("00000000-0000-0000-0000-0000000000aa",)])
    _patch_psycopg_connect(monkeypatch, cursor)

    candidate_id = await create_candidate(
        "postgres://x",
        workspace_id="w1",
        run_id="r1",
        rank=1,
        source="proteina_complexa",
        title="Binder design 1",
        sequence="GGGG",
        artifact_id="art-1",
        parent_inference_id="inf-1",
    )

    assert candidate_id == "00000000-0000-0000-0000-0000000000aa"
    sql, params = cursor.executes[0]
    assert "insert into autopep_protein_candidate" in sql
    assert "proteina_complexa" in params
    assert "Binder design 1" in params
    assert "GGGG" in params
    assert 1 in params
    assert "art-1" in params
    assert "inf-1" in params


@pytest.mark.asyncio
async def test_insert_candidate_scores_executes_one_insert_per_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The first cursor.fetchone() satisfies the tenant-isolation precondition
    # select, then the inserts run.
    cursor = _FakeCursor(returning=[(1,)])
    _patch_psycopg_connect(monkeypatch, cursor)

    rows = [
        {
            "candidate_id": "c1",
            "model_inference_id": "i1",
            "scorer": "dscript",
            "status": "ok",
            "label": None,
            "value": 0.74,
            "unit": "probability",
            "values_json": {"available": True},
            "warnings_json": [],
            "errors_json": [],
        },
        {
            "candidate_id": "c1",
            "model_inference_id": "i1",
            "scorer": "prodigy",
            "status": "ok",
            "label": None,
            "value": -7.4,
            "unit": "kcal/mol",
            "values_json": {"available": True},
            "warnings_json": [],
            "errors_json": [],
        },
    ]

    await insert_candidate_scores(
        "postgres://x",
        workspace_id="w1",
        run_id="r1",
        candidate_id="c1",
        model_inference_id="i1",
        rows=rows,
    )

    # 1 precondition (select 1 ...) + 2 inserts = 3 executes.
    assert len(cursor.executes) == 3
    precondition_sql, precondition_params = cursor.executes[0]
    assert "select 1" in precondition_sql
    assert "autopep_protein_candidate" in precondition_sql
    assert "w1" in precondition_params
    assert "r1" in precondition_params
    assert "c1" in precondition_params
    for sql, params in cursor.executes[1:]:
        assert "insert into autopep_candidate_score" in sql
        assert "w1" in params
        assert "r1" in params
        assert "c1" in params
        assert "i1" in params


@pytest.mark.asyncio
async def test_insert_candidate_scores_raises_when_candidate_not_in_workspace_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Precondition select returns no row -> tenant isolation violation.
    cursor = _FakeCursor(returning=[None])
    _patch_psycopg_connect(monkeypatch, cursor)

    rows = [
        {
            "candidate_id": "c-other",
            "model_inference_id": "i1",
            "scorer": "dscript",
            "status": "ok",
            "label": None,
            "value": 0.7,
            "unit": "probability",
            "values_json": {"available": True},
            "warnings_json": [],
            "errors_json": [],
        },
    ]

    with pytest.raises(RuntimeError, match="candidate not found"):
        await insert_candidate_scores(
            "postgres://x",
            workspace_id="w1",
            run_id="r1",
            candidate_id="c-other",
            model_inference_id="i1",
            rows=rows,
        )

    # Only the precondition select ran — no inserts.
    assert len(cursor.executes) == 1
    sql, _ = cursor.executes[0]
    assert "select 1" in sql


@pytest.mark.asyncio
async def test_update_candidate_fold_artifact_scopes_to_workspace_and_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(rowcounts=[1])
    _patch_psycopg_connect(monkeypatch, cursor)

    await update_candidate_fold_artifact(
        "postgres://x",
        candidate_id="c1",
        workspace_id="w1",
        run_id="r1",
        fold_artifact_id="fold-1",
    )

    assert len(cursor.executes) == 1
    sql, params = cursor.executes[0]
    assert "update autopep_protein_candidate" in sql
    assert "workspace_id" in sql
    assert "run_id" in sql
    assert "c1" in params
    assert "w1" in params
    assert "r1" in params
    assert "fold-1" in params


@pytest.mark.asyncio
async def test_update_candidate_fold_artifact_raises_when_no_row_matched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(rowcounts=[0])
    _patch_psycopg_connect(monkeypatch, cursor)

    with pytest.raises(RuntimeError, match="candidate not found"):
        await update_candidate_fold_artifact(
            "postgres://x",
            candidate_id="c-other",
            workspace_id="w1",
            run_id="r1",
            fold_artifact_id="fold-1",
        )


# ---------------------------------------------------------------------------
# ToolRunContext (contextvar)
# ---------------------------------------------------------------------------


def _make_ctx() -> ToolRunContext:
    return ToolRunContext(
        workspace_id="w1",
        run_id="r1",
        database_url="postgres://test",
        proteina_base_url="https://proteina.example/run",
        proteina_api_key="p-key",
        chai_base_url="https://chai.example/run",
        chai_api_key="c-key",
        scoring_base_url="https://score.example/run",
        scoring_api_key="s-key",
    )


def test_get_tool_run_context_raises_when_unset() -> None:
    # Reset the contextvar via setting and unsetting through a fresh token.
    from autopep_agent import run_context as run_context_mod

    token = run_context_mod._tool_run_context_var.set(None)
    try:
        with pytest.raises(RuntimeError, match="ToolRunContext"):
            get_tool_run_context()
    finally:
        run_context_mod._tool_run_context_var.reset(token)


def test_set_and_get_tool_run_context_round_trip() -> None:
    ctx = _make_ctx()
    set_tool_run_context(ctx)
    assert get_tool_run_context() is ctx


# ---------------------------------------------------------------------------
# LLM-visible signatures must NOT contain URL/API-key parameters
# ---------------------------------------------------------------------------


def test_generate_binder_candidates_schema_omits_endpoint_credentials() -> None:
    schema = biology_tools.generate_binder_candidates.params_json_schema
    properties = schema.get("properties", {})

    assert "proteina_base_url" not in properties
    assert "proteina_api_key" not in properties


def test_fold_sequences_with_chai_schema_omits_endpoint_credentials() -> None:
    schema = biology_tools.fold_sequences_with_chai.params_json_schema
    properties = schema.get("properties", {})

    assert "chai_base_url" not in properties
    assert "chai_api_key" not in properties


def test_score_candidate_interactions_schema_omits_endpoint_credentials() -> None:
    schema = biology_tools.score_candidate_interactions.params_json_schema
    properties = schema.get("properties", {})

    assert "scoring_base_url" not in properties
    assert "scoring_api_key" not in properties


# ---------------------------------------------------------------------------
# Biology tool persistence wiring
# ---------------------------------------------------------------------------


def _atom_line(serial: int, atom: str, residue: str, chain: str, number: int) -> str:
    return (
        f"ATOM  {serial:5d} {atom:<4} {residue:>3} {chain}{number:4d}"
        "      11.104  13.207  14.329  1.00 20.00           C"
    )


PDB_TEXT = "\n".join(
    [
        _atom_line(1, "N", "ALA", "A", 1),
        _atom_line(2, "CA", "ALA", "A", 1),
        _atom_line(3, "N", "GLY", "B", 2),
        _atom_line(4, "CA", "GLY", "B", 2),
    ],
)


class _DBHelperRecorder:
    """Records calls and returns canned ids to fake out the DB helpers."""

    def __init__(self) -> None:
        self.inference_calls: list[dict[str, Any]] = []
        self.complete_calls: list[dict[str, Any]] = []
        self.artifact_calls: list[dict[str, Any]] = []
        self.candidate_calls: list[dict[str, Any]] = []
        self.score_calls: list[dict[str, Any]] = []
        self.fold_calls: list[dict[str, Any]] = []
        self._inference_counter = 0
        self._artifact_counter = 0
        self._candidate_counter = 0

    async def create_model_inference(self, _url: str, **kwargs: Any) -> str:
        self.inference_calls.append(kwargs)
        self._inference_counter += 1
        return f"inference-{self._inference_counter}"

    async def complete_model_inference(self, _url: str, **kwargs: Any) -> None:
        self.complete_calls.append(kwargs)

    async def create_artifact(self, _url: str, **kwargs: Any) -> str:
        self.artifact_calls.append(kwargs)
        self._artifact_counter += 1
        return f"artifact-{self._artifact_counter}"

    async def create_candidate(self, _url: str, **kwargs: Any) -> str:
        self.candidate_calls.append(kwargs)
        self._candidate_counter += 1
        return f"candidate-{self._candidate_counter}"

    async def insert_candidate_scores(self, _url: str, **kwargs: Any) -> None:
        self.score_calls.append(kwargs)

    async def update_candidate_fold_artifact(self, _url: str, **kwargs: Any) -> None:
        self.fold_calls.append(kwargs)


class _FakeEventWriter:
    def __init__(self, _database_url: str) -> None:
        self.events: list[dict[str, Any]] = []

    async def append_event(
        self,
        *,
        run_id: str,
        event_type: str,
        title: str,
        summary: str | None = None,
        display: dict[str, Any] | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            {
                "run_id": run_id,
                "type": event_type,
                "title": title,
                "summary": summary,
                "display": display,
                "raw": raw,
            },
        )


def _wire_persistence_doubles(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_DBHelperRecorder, _FakeEventWriter]:
    recorder = _DBHelperRecorder()
    writer = _FakeEventWriter("postgres://test")

    monkeypatch.setattr(
        biology_tools, "create_model_inference", recorder.create_model_inference,
    )
    monkeypatch.setattr(
        biology_tools, "complete_model_inference", recorder.complete_model_inference,
    )
    monkeypatch.setattr(biology_tools, "create_artifact", recorder.create_artifact)
    monkeypatch.setattr(biology_tools, "create_candidate", recorder.create_candidate)
    monkeypatch.setattr(
        biology_tools,
        "insert_candidate_scores",
        recorder.insert_candidate_scores,
    )
    monkeypatch.setattr(
        biology_tools,
        "update_candidate_fold_artifact",
        recorder.update_candidate_fold_artifact,
    )

    # Replace the EventWriter constructor so all tools see the same writer.
    def make_writer(_url: str) -> _FakeEventWriter:
        return writer

    monkeypatch.setattr(biology_tools, "EventWriter", make_writer)
    return recorder, writer


async def _fake_r2_put(
    *_args: Any, **_kwargs: Any,
) -> str:
    return "decafbad" * 8  # fake sha256


_BIOLOGY_TOOL_ENV = {
    "DATABASE_URL": "postgresql://test:test@db.example/autopep",
    "R2_BUCKET": "autopep-test",
    "R2_ACCOUNT_ID": "account",
    "R2_ACCESS_KEY_ID": "ak",
    "R2_SECRET_ACCESS_KEY": "sk",
    "MODAL_PROTEINA_URL": "https://proteina.example/run",
    "MODAL_PROTEINA_API_KEY": "p",
    "MODAL_CHAI_URL": "https://chai.example/run",
    "MODAL_CHAI_API_KEY": "c",
    "MODAL_PROTEIN_INTERACTION_SCORING_URL": "https://score.example/run",
    "MODAL_PROTEIN_INTERACTION_SCORING_API_KEY": "s",
    "OPENAI_API_KEY": "openai-test",
}


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _BIOLOGY_TOOL_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.mark.asyncio
async def test_generate_binder_candidates_persists_inference_artifact_and_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    recorder, writer = _wire_persistence_doubles(monkeypatch)
    monkeypatch.setattr(biology_tools, "r2_put_object", _fake_r2_put)

    response = {"pdbs": [{"filename": "design-1.pdb", "pdb": PDB_TEXT}]}

    class FakeProteinaClient:
        def __init__(self, base_url: str, api_key: str) -> None:
            self.base_url = base_url
            self.api_key = api_key

        async def design(self, **_kwargs: Any) -> dict[str, Any]:
            return response

    monkeypatch.setattr(biology_tools, "ProteinaClient", FakeProteinaClient)

    set_tool_run_context(_make_ctx())

    result = await biology_tools._generate_binder_candidates(
        target_structure="target-pdb",
        target_filename="target.pdb",
        target_input="A",
        hotspot_residues=["A:42"],
        binder_length_min=55,
        binder_length_max=88,
    )

    assert result["candidates"][0]["sequence"] == "G"
    # Inference recorded.
    assert len(recorder.inference_calls) == 1
    assert recorder.inference_calls[0]["model_name"] == "proteina_complexa"
    assert len(recorder.complete_calls) == 1
    assert recorder.complete_calls[0]["status"] == "completed"
    # Artifact + candidate recorded with parent_inference_id wired through.
    assert len(recorder.artifact_calls) == 1
    art_call = recorder.artifact_calls[0]
    assert art_call["kind"] == "proteina_result"
    assert art_call["content_type"] == "chemical/x-pdb"
    assert len(recorder.candidate_calls) == 1
    cand_call = recorder.candidate_calls[0]
    assert cand_call["source"] == "proteina_complexa"
    assert cand_call["rank"] == 1
    assert cand_call["sequence"] == "G"
    assert cand_call["artifact_id"] == "artifact-1"
    assert cand_call["parent_inference_id"] == "inference-1"
    # Events appended.
    types = [e["type"] for e in writer.events]
    assert "artifact_created" in types
    assert "candidate_ranked" in types

    # The returned candidate now also carries its DB id.
    assert result["candidates"][0]["candidate_id"] == "candidate-1"


@pytest.mark.asyncio
async def test_generate_binder_candidates_marks_inference_failed_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    recorder, _writer = _wire_persistence_doubles(monkeypatch)
    monkeypatch.setattr(biology_tools, "r2_put_object", _fake_r2_put)

    class BoomProteinaClient:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        async def design(self, **_kwargs: Any) -> Any:
            raise RuntimeError("proteina exploded")

    monkeypatch.setattr(biology_tools, "ProteinaClient", BoomProteinaClient)

    set_tool_run_context(_make_ctx())

    with pytest.raises(RuntimeError, match="proteina exploded"):
        await biology_tools._generate_binder_candidates(
            target_structure="x",
            target_filename="x.pdb",
            target_input=None,
            hotspot_residues=[],
            binder_length_min=10,
            binder_length_max=20,
        )

    # Inference was started, then completed with status='failed'.
    assert len(recorder.inference_calls) == 1
    assert len(recorder.complete_calls) == 1
    assert recorder.complete_calls[0]["status"] == "failed"
    assert recorder.complete_calls[0]["error_summary"]


@pytest.mark.asyncio
async def test_generate_binder_candidates_marks_inference_failed_when_persistence_loop_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    recorder, _writer = _wire_persistence_doubles(monkeypatch)

    # client.design returns successfully ...
    response = {"pdbs": [{"filename": "design-1.pdb", "pdb": PDB_TEXT}]}

    class FakeProteinaClient:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        async def design(self, **_kwargs: Any) -> dict[str, Any]:
            return response

    monkeypatch.setattr(biology_tools, "ProteinaClient", FakeProteinaClient)

    # ... but the persistence loop blows up mid-way (R2 upload fails).
    async def boom_r2_put(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("r2 upload exploded")

    monkeypatch.setattr(biology_tools, "r2_put_object", boom_r2_put)

    set_tool_run_context(_make_ctx())

    with pytest.raises(RuntimeError, match="r2 upload exploded"):
        await biology_tools._generate_binder_candidates(
            target_structure="x",
            target_filename="x.pdb",
            target_input=None,
            hotspot_residues=[],
            binder_length_min=10,
            binder_length_max=20,
        )

    # Inference must end up failed, not completed — the persistence loop is
    # part of the inference's success criteria.
    assert len(recorder.inference_calls) == 1
    assert len(recorder.complete_calls) == 1
    assert recorder.complete_calls[0]["status"] == "failed"
    assert recorder.complete_calls[0]["error_summary"]


@pytest.mark.asyncio
async def test_fold_sequences_with_chai_persists_inference_and_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    recorder, writer = _wire_persistence_doubles(monkeypatch)
    monkeypatch.setattr(biology_tools, "r2_put_object", _fake_r2_put)

    response = {
        "cifs": [
            {"filename": "candidate-1.cif", "cif": "data_block\n#"},
        ],
    }

    class FakeChaiClient:
        def __init__(self, base_url: str, api_key: str) -> None:
            self.base_url = base_url
            self.api_key = api_key

        async def predict(self, fasta: str, num_diffn_samples: int = 1) -> Any:
            return response

    monkeypatch.setattr(biology_tools, "ChaiClient", FakeChaiClient)

    set_tool_run_context(_make_ctx())

    await biology_tools._fold_sequences_with_chai(
        sequence_candidates=[
            {
                "id": "candidate-1",
                "sequence": " acde ",
                "candidate_id": "db-candidate-1",
            },
        ],
    )

    # Inference recorded with chai_1 model_name.
    assert len(recorder.inference_calls) == 1
    assert recorder.inference_calls[0]["model_name"] == "chai_1"
    assert len(recorder.complete_calls) == 1
    assert recorder.complete_calls[0]["status"] == "completed"

    # Artifact recorded for the returned CIF.
    assert len(recorder.artifact_calls) == 1
    assert recorder.artifact_calls[0]["kind"] == "chai_result"

    # Candidate fold link updated.
    assert len(recorder.fold_calls) == 1
    assert recorder.fold_calls[0]["candidate_id"] == "db-candidate-1"
    assert recorder.fold_calls[0]["fold_artifact_id"] == "artifact-1"

    types = [e["type"] for e in writer.events]
    assert "artifact_created" in types


@pytest.mark.asyncio
async def test_fold_sequences_with_chai_links_ordered_response_when_filename_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    recorder, _writer = _wire_persistence_doubles(monkeypatch)
    monkeypatch.setattr(biology_tools, "r2_put_object", _fake_r2_put)

    response = {
        "cifs": [
            {"filename": "rank_1_pred.model_idx_0.cif", "cif": "data_block\n#"},
        ],
    }

    class FakeChaiClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def predict(self, fasta: str, num_diffn_samples: int = 1) -> Any:
            return response

    monkeypatch.setattr(biology_tools, "ChaiClient", FakeChaiClient)

    set_tool_run_context(_make_ctx())

    await biology_tools._fold_sequences_with_chai(
        sequence_candidates=[
            {
                "id": "candidate-1",
                "sequence": "ACDE",
                "candidate_id": "db-candidate-1",
            },
        ],
    )

    assert len(recorder.fold_calls) == 1
    assert recorder.fold_calls[0]["candidate_id"] == "db-candidate-1"
    assert recorder.fold_calls[0]["fold_artifact_id"] == "artifact-1"


@pytest.mark.asyncio
async def test_fold_sequences_with_chai_marks_inference_failed_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    recorder, _writer = _wire_persistence_doubles(monkeypatch)
    monkeypatch.setattr(biology_tools, "r2_put_object", _fake_r2_put)

    class BoomChaiClient:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        async def predict(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("chai exploded")

    monkeypatch.setattr(biology_tools, "ChaiClient", BoomChaiClient)

    set_tool_run_context(_make_ctx())

    with pytest.raises(RuntimeError, match="chai exploded"):
        await biology_tools._fold_sequences_with_chai(
            sequence_candidates=[
                {
                    "id": "candidate-1",
                    "sequence": "ACDE",
                    "candidate_id": "db-candidate-1",
                },
            ],
        )

    assert len(recorder.inference_calls) == 1
    assert len(recorder.complete_calls) == 1
    assert recorder.complete_calls[0]["status"] == "failed"
    assert recorder.complete_calls[0]["error_summary"]


@pytest.mark.asyncio
async def test_score_candidate_interactions_persists_score_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder, _writer = _wire_persistence_doubles(monkeypatch)

    scoring_response = {
        "results": [
            {
                "id": "candidate-1",
                "candidate_id": "db-candidate-1",
                "status": "ok",
                "scores": {
                    "dscript": {"available": True, "interaction_probability": 0.6},
                    "prodigy": {
                        "available": True,
                        "delta_g_kcal_per_mol": -5.2,
                        "kd_molar": 1e-5,
                    },
                },
                "aggregate": {"available": True, "label": "likely_binder"},
                "warnings": [],
                "errors": [],
            },
        ],
    }

    class FakeScoringClient:
        def __init__(self, base_url: str, api_key: str) -> None:
            self.base_url = base_url
            self.api_key = api_key

        async def score_batch(self, items: list[dict[str, Any]]) -> Any:
            return scoring_response

    monkeypatch.setattr(biology_tools, "ScoringClient", FakeScoringClient)

    set_tool_run_context(_make_ctx())

    await biology_tools._score_candidate_interactions(
        target_name="target",
        target_sequence="AAAA",
        candidates=[
            {
                "id": "candidate-1",
                "candidate_id": "db-candidate-1",
                "sequence": "GG",
                "pdb": PDB_TEXT,
            },
        ],
    )

    assert len(recorder.inference_calls) == 1
    assert recorder.inference_calls[0]["model_name"] == "protein_interaction_scoring"
    assert len(recorder.complete_calls) == 1
    assert recorder.complete_calls[0]["status"] == "completed"

    # One insert_candidate_scores call per result row.
    assert len(recorder.score_calls) == 1
    call = recorder.score_calls[0]
    assert call["candidate_id"] == "db-candidate-1"
    rows = call["rows"]
    assert {row["scorer"] for row in rows} == {
        "dscript",
        "prodigy",
        "protein_interaction_aggregate",
    }


@pytest.mark.asyncio
async def test_score_candidate_interactions_marks_inference_failed_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    recorder, _writer = _wire_persistence_doubles(monkeypatch)

    class BoomScoringClient:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        async def score_batch(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("scoring exploded")

    monkeypatch.setattr(biology_tools, "ScoringClient", BoomScoringClient)

    set_tool_run_context(_make_ctx())

    with pytest.raises(RuntimeError, match="scoring exploded"):
        await biology_tools._score_candidate_interactions(
            target_name="target",
            target_sequence="AAAA",
            candidates=[
                {
                    "id": "candidate-1",
                    "candidate_id": "db-candidate-1",
                    "sequence": "GG",
                    "pdb": PDB_TEXT,
                },
            ],
        )

    assert len(recorder.inference_calls) == 1
    assert len(recorder.complete_calls) == 1
    assert recorder.complete_calls[0]["status"] == "failed"
    assert recorder.complete_calls[0]["error_summary"]


# ---------------------------------------------------------------------------
# Runner sets ToolRunContext before invoking Runner.run_streamed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_run_sets_tool_run_context_before_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from autopep_agent import runner as runner_mod
    from autopep_agent.db import AgentRunContext

    required_env = {
        "DATABASE_URL": "postgresql://test:test@db.example/autopep",
        "R2_BUCKET": "autopep-test",
        "R2_ACCOUNT_ID": "account",
        "R2_ACCESS_KEY_ID": "ak",
        "R2_SECRET_ACCESS_KEY": "sk",
        "MODAL_PROTEINA_URL": "https://proteina.example/run",
        "MODAL_PROTEINA_API_KEY": "p",
        "MODAL_CHAI_URL": "https://chai.example/run",
        "MODAL_CHAI_API_KEY": "c",
        "MODAL_PROTEIN_INTERACTION_SCORING_URL": "https://score.example/run",
        "MODAL_PROTEIN_INTERACTION_SCORING_API_KEY": "s",
        "OPENAI_API_KEY": "openai-test",
    }
    for key, value in required_env.items():
        monkeypatch.setenv(key, value)

    captured_ctx: dict[str, ToolRunContext] = {}

    class _FakeStreamedRun:
        def stream_events(self) -> Any:
            # Capture the context as it would be visible inside the agent loop.
            captured_ctx["ctx"] = get_tool_run_context()
            return iter([])

    runner_double = MagicMock()
    runner_double.run_streamed = MagicMock(return_value=_FakeStreamedRun())
    monkeypatch.setattr(runner_mod, "Runner", runner_double)
    monkeypatch.setattr(runner_mod, "_build_run_config", lambda **_kwargs: object())

    class _FakeWriter:
        def __init__(self, _url: str) -> None:
            pass

        async def append_event(self, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(runner_mod, "EventWriter", _FakeWriter)

    async def fake_get_run_context(*_a: Any, **_k: Any) -> AgentRunContext:
        return AgentRunContext(
            prompt="hi",
            model="gpt-5.5",
            task_kind="chat",
            enabled_recipes=[],
        )

    async def fake_claim_run(*_a: Any, **_k: Any) -> bool:
        return True

    async def fake_mark_completed(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(runner_mod, "get_run_context", fake_get_run_context)
    monkeypatch.setattr(runner_mod, "claim_run", fake_claim_run)
    monkeypatch.setattr(runner_mod, "mark_run_completed", fake_mark_completed)

    await runner_mod.execute_run(run_id="r1", thread_id="t1", workspace_id="w1")

    assert "ctx" in captured_ctx
    ctx = captured_ctx["ctx"]
    assert ctx.workspace_id == "w1"
    assert ctx.run_id == "r1"
    assert ctx.proteina_base_url == "https://proteina.example/run"
    assert ctx.chai_api_key == "c"
