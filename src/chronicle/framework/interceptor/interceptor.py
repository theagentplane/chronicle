"""The interceptor: the one crossing lifecycle (design sections 4.1, 6.1, 6.2 and 7.2).

``@boundary``, ``wrap``, ``wrap_llm`` and the instrumenters all go through this class. **Today**
(0.5.0) the lifecycle was copy-pasted about six times and ``wrap`` skipped hooks and failure
capture; here there is a single implementation, so ``wrap`` gains both.

Lifecycle of one crossing in a RECORD session (design 6.1):

1. capture the input; with ``emit_open`` send the open write
2. run ``enter`` hooks (may patch keyword arguments or abort)
3. call the wrapped function (sync or async)
4. build the output through the kind and adapter; on an exception record ``failure`` and re-raise
5. redact, close the envelope and enqueue the write
6. run ``crossing`` and ``record`` hooks, then ``leave``

In a REPLAY session a STUB crossing returns the recording and fires no hooks, and a RUN crossing
executes the real function, fires hooks, writes nothing and keeps input and result in memory.

Transparency (principle P3): the caller always gets the real return value or the real exception.
Nothing in recording is allowed to change that; every recording step is guarded. The only
deliberate exception is ``AbortCall`` raised by a hook.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from agentplane_primitives.enums import LinkType, Status
from agentplane_primitives.models import Envelope, Link
from agentplane_primitives.utils import new_envelope_id
from pydantic import JsonValue

from chronicle.framework.boundary_enums import BoundaryMode
from chronicle.framework.boundary_spec_types import BoundarySpec
from chronicle.framework.context.context_vars import attempt_var, envelope_stack_var
from chronicle.framework.context.recording_session import RecordingSession
from chronicle.framework.errors import RecordedCallError
from chronicle.framework.hooks.hook_runner_utils import (
    run_crossing,
    run_enter,
    run_leave,
    run_record,
)
from chronicle.framework.hooks.hook_types import CallInfo
from chronicle.framework.interceptor.argument_binding_utils import bind_arguments
from chronicle.framework.interceptor.crossing_types import Crossing
from chronicle.framework.interceptor.envelope_builder_utils import (
    build_closed_envelope,
    build_metadata,
    build_open_envelope,
    error_output,
    prepare_input,
    prepare_output,
)
from chronicle.framework.kinds.kind_registry import strategy_for
from chronicle.framework.kinds.kind_strategy_types import KindStrategy
from chronicle.framework.serialization.json_utils import to_json
from chronicle.timing_utils import utc_now

_log = logging.getLogger("chronicle")

SessionProvider = Callable[[], RecordingSession]


class Interceptor:
    """Runs a boundary's crossings against the active recording session."""

    def __init__(self, session_provider: SessionProvider) -> None:
        self._session_provider = session_provider

    # ------------------------------------------------------------------ public entry points

    def call(
        self,
        spec: BoundarySpec,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Run one synchronous crossing of ``spec`` around ``fn(*args, **kwargs)``."""
        session = self._session_provider()
        crossing = self._begin(session, spec, args, kwargs)
        if crossing is None:
            return fn(*args, **kwargs)
        if isinstance(crossing, _Stubbed):
            return crossing.value
        call_kwargs = self._enter(crossing, kwargs)
        try:
            result = self._run_sync(crossing, fn, args, call_kwargs)
            self._complete(crossing, result)
            return result
        finally:
            self._leave(crossing)

    async def acall(
        self,
        spec: BoundarySpec,
        fn: Callable[..., Awaitable[Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Run one asynchronous crossing of ``spec`` around ``await fn(*args, **kwargs)``."""
        session = self._session_provider()
        crossing = self._begin(session, spec, args, kwargs)
        if crossing is None:
            return await fn(*args, **kwargs)
        if isinstance(crossing, _Stubbed):
            return crossing.value
        call_kwargs = self._enter(crossing, kwargs)
        try:
            result = await self._run_async(crossing, fn, args, call_kwargs)
            self._complete(crossing, result)
            return result
        finally:
            self._leave(crossing)

    # ------------------------------------------------------------------------------ phases

    def _begin(
        self,
        session: RecordingSession,
        spec: BoundarySpec,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> "Crossing | _Stubbed | None":
        """Capture the input and decide what to do: ``None`` means plain passthrough."""
        recording = session.settings.recording and not session.is_replay
        if not recording and not session.is_replay and not len(session.hooks):
            return None
        arguments = _capture_arguments(spec, args, kwargs)
        strategy = strategy_for(spec.kind)
        if session.is_replay:
            return self._begin_replay(session, spec, strategy, arguments)
        attempt_info = attempt_var.get()
        links: list[Link] = []
        attempt_number = 1
        if attempt_info is not None:
            attempt_number = attempt_info[0]
            if attempt_info[1] is not None:
                links.append(Link(type=LinkType.RETRY_OF, envelope_id=attempt_info[1]))
        envelope_id = new_envelope_id()
        sequence = session.next_sequence()
        invocation = session.next_invocation(spec.name)
        stack = envelope_stack_var.get()
        crossing = Crossing(
            spec=spec,
            session=session,
            strategy=strategy,
            arguments=arguments,
            info=CallInfo(
                name=spec.name,
                kind=spec.kind,
                arguments=arguments,
                invocation_index=invocation,
                attempt=attempt_number,
                trace_id=session.trace_id,
                span_id=session.span_id,
                envelope_id=envelope_id,
            ),
            envelope_id=envelope_id,
            parent_envelope_id=stack[-1] if stack else None,
            started_at=utc_now(),
            sequence=sequence,
            invocation_index=invocation,
            attempt=attempt_number,
            links=links,
            recording=recording,
        )
        if recording and session.settings.emit_open:
            self._write_open(crossing)
        return crossing

    def _begin_replay(
        self,
        session: RecordingSession,
        spec: BoundarySpec,
        strategy: KindStrategy,
        arguments: dict[str, JsonValue],
    ) -> "Crossing | _Stubbed":
        control = session.replay
        if control is None:
            raise RuntimeError("a REPLAY session needs a replay control")
        index = control.next_invocation(spec.name)
        if control.mode_for(spec.name, index) is BoundaryMode.STUB:
            recorded = control.take(spec.name, index)
            output = recorded.output
            error = getattr(output, "error", None)
            if error is not None:
                raise RecordedCallError(
                    error.type, error.message, name=spec.name, invocation_index=index
                )
            return _Stubbed(strategy.stub_value(recorded))
        envelope_id = new_envelope_id()
        return Crossing(
            spec=spec,
            session=session,
            strategy=strategy,
            arguments=arguments,
            info=CallInfo(
                name=spec.name,
                kind=spec.kind,
                arguments=arguments,
                invocation_index=index,
                attempt=1,
                trace_id=session.trace_id,
                span_id=session.span_id,
                envelope_id=envelope_id,
            ),
            envelope_id=envelope_id,
            parent_envelope_id=None,
            started_at=utc_now(),
            sequence=0,
            invocation_index=index,
            attempt=1,
            recording=False,
        )

    def _enter(self, crossing: Crossing, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Run ``enter`` hooks; on an abort or failure record it and raise."""
        session = crossing.session
        try:
            patch = run_enter(session.hooks, crossing.info, session.settings.fail_call_on_error)
        except BaseException as exc:
            self._fail(crossing, exc)
            raise
        crossing.entered = True
        merged = dict(kwargs)
        merged.update(patch)
        return merged

    def _run_sync(
        self,
        crossing: Crossing,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        token = _push(crossing)
        try:
            return fn(*args, **kwargs)
        except BaseException as exc:
            self._fail(crossing, exc)
            raise
        finally:
            envelope_stack_var.reset(token)

    async def _run_async(
        self,
        crossing: Crossing,
        fn: Callable[..., Awaitable[Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        token = _push(crossing)
        try:
            return await fn(*args, **kwargs)
        except BaseException as exc:
            self._fail(crossing, exc)
            raise
        finally:
            envelope_stack_var.reset(token)

    def _complete(self, crossing: Crossing, result: Any) -> None:
        """The call returned: record it (RECORD) or capture it (REPLAY RUN), then ``crossing``."""
        session = crossing.session
        if session.is_replay:
            if session.replay is not None:
                session.replay.capture(
                    crossing.spec.name, crossing.invocation_index, crossing.arguments, result
                )
        elif crossing.recording:
            envelope = self._close_success(crossing, result)
            if envelope is not None:
                run_crossing(
                    session.hooks, crossing.info, result, session.settings.fail_call_on_error
                )
                run_record(session.hooks, envelope, session.settings.fail_call_on_error)
                return
        run_crossing(session.hooks, crossing.info, result, session.settings.fail_call_on_error)

    def _leave(self, crossing: Crossing) -> None:
        if crossing.entered:
            run_leave(
                crossing.session.hooks, crossing.info, crossing.session.settings.fail_call_on_error
            )

    # ------------------------------------------------------------------------- recording

    def _write_open(self, crossing: Crossing) -> None:
        try:
            _, input_model, truncated = prepare_input(crossing)
            self._emit(crossing, build_open_envelope(crossing, input_model, truncated))
        except Exception:
            _log.warning("chronicle could not write the open record", exc_info=True)

    def _close_success(self, crossing: Crossing, result: Any) -> Envelope | None:
        try:
            raw_input, input_model, in_truncated = prepare_input(crossing)
            output_model, extra, out_truncated = prepare_output(crossing, raw_input, result)
            metadata = build_metadata(crossing, extra, in_truncated or out_truncated)
            envelope = build_closed_envelope(
                crossing, input_model, output_model, Status.SUCCESS, metadata
            )
        except Exception:
            _log.warning("chronicle could not record %r", crossing.spec.name, exc_info=True)
            return None
        self._emit(crossing, envelope)
        return envelope

    def _fail(self, crossing: Crossing, exc: BaseException) -> None:
        """Record a failed crossing so incidents that raise are still reproducible."""
        if not crossing.recording or crossing.session.is_replay:
            return
        try:
            _raw_input, input_model, truncated = prepare_input(crossing)
            output_model = crossing.strategy.build_error(error_output(crossing, exc))
            metadata = build_metadata(crossing, None, truncated)
            envelope = build_closed_envelope(
                crossing, input_model, output_model, Status.FAILURE, metadata
            )
        except Exception:
            _log.warning("chronicle could not record the failure", exc_info=True)
            return
        self._emit(crossing, envelope)
        try:
            run_record(
                crossing.session.hooks, envelope, crossing.session.settings.fail_call_on_error
            )
        except Exception:
            _log.warning("chronicle record hook failed", exc_info=True)

    def _emit(self, crossing: Crossing, envelope: Envelope) -> None:
        """Hand the record to the sink; a delivery problem never breaks the agent here."""
        sink = crossing.session.sink
        if sink is None:
            return
        try:
            sink.write_envelope(envelope)
        except Exception:
            _log.warning("chronicle could not enqueue an envelope", exc_info=True)


class _Stubbed:
    """The crossing was served from the recording: this is the value to hand back."""

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


def _push(crossing: Crossing) -> Any:
    return envelope_stack_var.set((*envelope_stack_var.get(), crossing.envelope_id))


def _capture_arguments(
    spec: BoundarySpec, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, JsonValue]:
    """The JSON form of the call's arguments by name. Never raises."""
    if spec.extract_input is not None:
        try:
            captured = spec.extract_input(*args, **kwargs)
            value = to_json(dict(captured))
            return value if isinstance(value, dict) else {}
        except Exception:
            _log.warning("chronicle extract_input failed for %r", spec.name, exc_info=True)
    return bind_arguments(spec.signature, args, kwargs)
