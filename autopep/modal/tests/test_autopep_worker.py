from __future__ import annotations


def test_run_stream_endpoint_is_defined() -> None:
    from autopep_worker import run_stream

    assert run_stream is not None


def test_start_run_endpoint_is_defined() -> None:
    from autopep_worker import start_run

    assert start_run is not None


def test_run_autopep_agent_function_is_defined() -> None:
    from autopep_worker import run_autopep_agent

    assert run_autopep_agent is not None
