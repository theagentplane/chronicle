"""Chronicle CLI — record, extract, replay, and verify agent envelopes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from chronicle.envelope.schema import Envelope
from chronicle.envelope.store import EnvelopeStore
from chronicle.judge.runner import JudgeRunner, MockJudgeClient, OpenAIJudgeClient
from chronicle.replay.injector import ReplayInjector


@click.group()
@click.version_option()
def main() -> None:
    """Chronicle: Agent Data Recorder and Verification Test Bench."""


@main.command()
@click.option("--store", default=".chronicle/runs/envelopes.jsonl", help="Envelope store path")
@click.option("--phoenix/--no-phoenix", default=True, help="Export traces to Phoenix")
@click.option("--service", default="chronicle", help="OTel service name")
def record(store: str, phoenix: bool, service: str) -> None:
    """Bootstrap tracing and envelope recording for an agent session."""
    from chronicle.instrumentation import bootstrap_tracing, instrument_langchain

    bootstrap_tracing(
        service_name=service,
        phoenix_endpoint="http://localhost:4317" if phoenix else False,
    )
    try:
        instrument_langchain()
        click.echo("OpenInference LangChain instrumentation enabled.")
    except ImportError:
        click.echo("LangChain instrumentation unavailable (install chronicle[langgraph]).")

    click.echo(f"Envelope store: {store}")
    click.echo("Set CHRONICLE_BUILD_ID to pin runtime build metadata.")
    click.echo("Recording ready — instrument your agent nodes with EnvelopeRecorder.")


@main.command()
@click.option("--trace-id", required=True, help="Trace ID to extract")
@click.option("--store", default=".chronicle/runs/envelopes.jsonl", help="Source envelope store")
@click.option(
    "--output",
    default="fixtures/envelopes",
    help="Destination directory for regression fixtures",
)
def extract(trace_id: str, store: str, output: str) -> None:
    """Extract envelopes from a trace into committed regression fixtures."""
    envelope_store = EnvelopeStore(store)
    paths = envelope_store.export_trace(trace_id, output)
    if not paths:
        click.echo(f"No envelopes found for trace_id={trace_id}", err=True)
        sys.exit(1)
    click.echo(f"Exported {len(paths)} envelope(s) to {output}/")
    for p in paths:
        click.echo(f"  {p}")


@main.command()
@click.argument("fixture", type=click.Path(exists=True))
def replay(fixture: str) -> None:
    """Run Layer 1 deterministic replay against an envelope fixture."""
    envelope = Envelope.from_file(fixture)
    injector = ReplayInjector(envelope)

    def _identity_agent(state: dict, inj: ReplayInjector) -> dict:
        completion = inj.stub_llm()
        for tc in envelope.action_result.tool_calls:
            inj.stub_tool(tc.name, tc.arguments)
        return {
            "completion": completion.completion,
            "finish_reason": completion.finish_reason,
            "tool_calls": [tc.model_dump() for tc in completion.tool_calls],
        }

    result, ctx, assertions = injector.replay(_identity_agent)
    passed = all(a.passed for a in assertions)
    for a in assertions:
        status = click.style("PASS", fg="green") if a.passed else click.style("FAIL", fg="red")
        click.echo(f"  [{status}] {a.name}: {a.message}")

    if not passed:
        sys.exit(1)
    click.echo(click.style("Layer 1 replay passed.", fg="green"))


@main.command()
@click.argument("fixture", type=click.Path(exists=True))
@click.option("--layer2/--no-layer2", default=False, help="Run Layer 2 LLM-as-judge")
@click.option("--judge-model", default="gpt-4o-mini", help="Judge model for Layer 2")
@click.option("--mock-judge", is_flag=True, help="Use mock judge (no API calls)")
def verify(fixture: str, layer2: bool, judge_model: str, mock_judge: bool) -> None:
    """Run Layer 1 replay and optionally Layer 2 evaluation."""
    ctx = click.get_current_context()
    ctx.invoke(replay, fixture=fixture)

    if not layer2:
        return

    envelope = Envelope.from_file(fixture)
    if mock_judge:
        client = MockJudgeClient()
    else:
        client = OpenAIJudgeClient(model=judge_model)

    runner = JudgeRunner(client)
    eval_result = runner.evaluate(envelope)
    for score in eval_result.scores:
        status = click.style("PASS", fg="green") if score.passed else click.style("FAIL", fg="red")
        click.echo(f"  [{status}] {score.criterion.value}: {score.score:.2f} — {score.rationale}")

    if not eval_result.overall_passed:
        click.echo(click.style("Layer 2 evaluation failed.", fg="red"))
        sys.exit(1)
    click.echo(click.style("Layer 2 evaluation passed.", fg="green"))


@main.command("schema")
def schema_cmd() -> None:
    """Print the Envelope JSON Schema."""
    click.echo(json.dumps(Envelope.json_schema(), indent=2))


@main.command("list-fixtures")
@click.option("--directory", default="fixtures/envelopes", help="Fixtures directory")
def list_fixtures(directory: str) -> None:
    """List committed regression envelope fixtures."""
    paths = EnvelopeStore.list_fixtures(directory)
    if not paths:
        click.echo(f"No fixtures in {directory}")
        return
    for p in paths:
        envelope = Envelope.from_file(str(p))
        click.echo(f"{p.name}  trace={envelope.trace_id}  node={envelope.node_id}")


if __name__ == "__main__":
    main()
