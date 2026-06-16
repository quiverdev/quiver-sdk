"""
AgentRuntime / Agent — the core agentic loop.
Mirrors AgentRuntime from @quiver/agents.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterable,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

from quiver_sdk.exceptions import AgentRuntimeAbortError, ControlledStopError
from quiver_sdk.llms.gateway import DefaultGateway, GatewayModelAdapter, create_gateway
from quiver_sdk.types import (
    AgentBeforeModelResult,
    AgentBeforeToolResult,
    AgentAfterToolResult,
    AgentMessage,
    AgentMessagePart,
    AgentModel,
    AgentModelEvent,
    AgentModelFinishReason,
    AgentModelRequest,
    AgentRunResult,
    AgentRuntimePlugin,
    AgentRuntimePluginContext,
    AgentRuntimeStateSnapshot,
    AgentStopControl,
    AgentTool,
    AgentToolCallPart,
    AgentToolContext,
    AgentToolDefinition,
    AgentToolResult,
    AgentUsage,
    GatewayProviderConfig,
    ToolApprovalRequest,
    ToolApprovalResult,
    ToolPolicy,
)
from quiver_sdk.utils import clone_messages, clone_usage, create_uid, text_from_message

AgentRunInput = Union[str, AgentMessage, List[AgentMessage]]
AgentEventListener = Callable[[Dict[str, Any]], None]

MAX_OUTPUT_SIZE = 50_000


def _create_message(
    role: str,
    content: List[AgentMessagePart],
    metadata: Optional[Dict[str, Any]] = None,
) -> AgentMessage:
    return AgentMessage(
        id=create_uid("msg"),
        role=role,
        content=content,
        created_at=int(time.time() * 1000),
        metadata=metadata,
    )


def _clone_usage(usage: AgentUsage) -> AgentUsage:
    return AgentUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        total_cost=usage.total_cost,
    )


def _normalize_input(inp: AgentRunInput) -> List[AgentMessage]:
    if isinstance(inp, str):
        return [_create_message("user", [{"type": "text", "text": inp}])]
    if isinstance(inp, list):
        return clone_messages(inp)
    return clone_messages([inp])


def _safe_json_size(value: Any) -> int:
    try:
        return len(json.dumps(value))
    except Exception:
        return len(str(value))


def _get_output_size(output: Any) -> int:
    if isinstance(output, str):
        return len(output)
    return _safe_json_size(output)


def _text_from_tool_message(message: Optional[AgentMessage]) -> str:
    if message is None:
        return ""
    for part in message.content:
        if isinstance(part, dict) and part.get("type") == "tool-result":
            if part.get("isError") or part.get("is_error"):
                return ""
            output = part.get("output", "")
            if isinstance(output, str):
                return output
            try:
                return json.dumps(output)
            except Exception:
                return str(output)
    return ""


def _usage_delta(start: AgentUsage, end: AgentUsage) -> Optional[Dict[str, Any]]:
    input_d = max(0, end.input_tokens - start.input_tokens)
    output_d = max(0, end.output_tokens - start.output_tokens)
    cache_r_d = max(0, end.cache_read_tokens - start.cache_read_tokens)
    cache_w_d = max(0, end.cache_write_tokens - start.cache_write_tokens)
    cost_d = max(0.0, (end.total_cost or 0.0) - (start.total_cost or 0.0))

    if not any([input_d, output_d, cache_r_d, cache_w_d, cost_d]):
        return None
    result: Dict[str, Any] = {
        "input_tokens": input_d,
        "output_tokens": output_d,
        "cache_read_tokens": cache_r_d,
        "cache_write_tokens": cache_w_d,
    }
    if cost_d > 0:
        result["cost"] = cost_d
    return result


def _merge_tool_metadata(existing: Any, new: Any) -> Any:
    if existing is None:
        return new
    if new is None:
        return existing
    if isinstance(existing, dict) and isinstance(new, dict):
        return {**existing, **new}
    return new


class AgentRuntime:
    """
    The core agentic loop.

    Manages conversation state, model streaming, tool execution, hooks, and plugins.

    Usage::

        agent = AgentRuntime(
            provider_id="anthropic",
            model_id="claude-sonnet-4-6",
            api_key="sk-ant-...",
            system_prompt="You are a helpful assistant.",
            tools=[my_tool],
        )
        result = await agent.run("What is 2 + 2?")
        print(result.output_text)
    """

    def __init__(
        self,
        # Provider config (simple form)
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        # OR pre-built model (advanced form)
        model: Optional[AgentModel] = None,
        # Agent config
        system_prompt: Optional[str] = None,
        tools: Optional[List[AgentTool]] = None,
        plugins: Optional[List[Any]] = None,
        hooks: Optional[Dict[str, Any]] = None,
        initial_messages: Optional[List[AgentMessage]] = None,
        max_iterations: Optional[int] = None,
        tool_execution: str = "sequential",
        tool_policies: Optional[Dict[str, ToolPolicy]] = None,
        tool_context_metadata: Optional[Dict[str, Any]] = None,
        model_options: Optional[Dict[str, Any]] = None,
        completion_policy: Optional[Dict[str, Any]] = None,
        logger: Optional[Any] = None,
        telemetry: Optional[Any] = None,
        agent_id: Optional[str] = None,
        agent_role: Optional[str] = None,
        parent_agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message_model_info: Optional[Dict[str, str]] = None,
        on_event: Optional[AgentEventListener] = None,
        # Advanced hooks
        prepare_turn: Optional[Callable] = None,
        consume_pending_user_message: Optional[Callable] = None,
        request_tool_approval: Optional[Callable] = None,
    ) -> None:
        # Build model
        if model is not None:
            self._model = model
        elif provider_id is not None:
            gateway = create_gateway(
                provider_configs=[
                    GatewayProviderConfig(
                        provider_id=provider_id,
                        api_key=api_key,
                        base_url=base_url,
                        headers=headers,
                    )
                ]
            )
            self._model = gateway.create_agent_model(provider_id, model_id)
        else:
            raise ValueError("Either 'model' or 'provider_id' must be provided.")

        self._system_prompt = system_prompt
        self._initial_tools = tools or []
        self._initial_plugins = plugins or []
        self._initial_hooks = hooks or {}
        self._initial_messages = clone_messages(initial_messages or [])
        self._max_iterations = max_iterations
        self._tool_execution = tool_execution
        self._tool_policies = tool_policies or {}
        self._tool_context_metadata = tool_context_metadata or {}
        self._model_options = model_options
        self._completion_policy = completion_policy or {}
        self._logger = logger
        self._telemetry = telemetry
        self._message_model_info = message_model_info
        self._prepare_turn = prepare_turn
        self._consume_pending_user_message_fn = consume_pending_user_message
        self._request_tool_approval = request_tool_approval

        # State
        self._agent_id = agent_id or create_uid("agent")
        self._agent_role = agent_role
        self._parent_agent_id = parent_agent_id
        self._conversation_id = conversation_id
        self._session_id = session_id

        self._status = "idle"
        self._run_id: Optional[str] = None
        self._iteration = 0
        self._messages: List[AgentMessage] = clone_messages(self._initial_messages)
        self._pending_tool_calls: List[str] = []
        self._usage = AgentUsage()
        self._last_error: Optional[str] = None

        # Tools registry (populated during initialize)
        self._tools: Dict[str, AgentTool] = {}

        # Hook bags
        self._hooks_before_run: List[Callable] = []
        self._hooks_after_run: List[Callable] = []
        self._hooks_before_model: List[Callable] = []
        self._hooks_after_model: List[Callable] = []
        self._hooks_before_tool: List[Callable] = []
        self._hooks_after_tool: List[Callable] = []
        self._hooks_on_event: List[Callable] = []

        # Event listeners
        self._listeners: Set[AgentEventListener] = set()
        if on_event:
            self._listeners.add(on_event)

        self._initialized = False
        self._abort_event: Optional[asyncio.Event] = None
        self._abort_reason: Optional[Any] = None

    @property
    def has_run(self) -> bool:
        """True after the first run() call."""
        return len(self._messages) > len(self._initial_messages) or self._status != "idle"

    def subscribe(self, listener: AgentEventListener) -> Callable[[], None]:
        """Subscribe to runtime events. Returns an unsubscribe function."""
        self._listeners.add(listener)
        def unsubscribe():
            self._listeners.discard(listener)
        return unsubscribe

    def abort(self, reason: Any = None) -> None:
        """Abort the current run."""
        if self._abort_event is None:
            return
        err = (
            reason
            if isinstance(reason, AgentRuntimeAbortError)
            else AgentRuntimeAbortError(reason)
        )
        self._last_error = err.args[0] if err.args else "Run aborted"
        self._abort_reason = err
        self._abort_event.set()

    def restore(self, messages: List[AgentMessage]) -> None:
        """Replace the conversation with a fresh set of messages."""
        self.abort("Agent state restored")
        self._run_id = None
        self._status = "idle"
        self._iteration = 0
        self._pending_tool_calls = []
        self._usage = AgentUsage()
        self._last_error = None
        self._messages = clone_messages(messages)
        self._initial_messages = clone_messages(messages)

    def snapshot(self) -> AgentRuntimeStateSnapshot:
        """Get a point-in-time snapshot of the runtime state."""
        return AgentRuntimeStateSnapshot(
            agent_id=self._agent_id,
            agent_role=self._agent_role,
            parent_agent_id=self._parent_agent_id,
            conversation_id=self._conversation_id,
            run_id=self._run_id,
            status=self._status,
            iteration=self._iteration,
            messages=clone_messages(self._messages),
            pending_tool_calls=list(self._pending_tool_calls),
            usage=_clone_usage(self._usage),
            last_error=self._last_error,
        )

    async def run(self, input: AgentRunInput) -> AgentRunResult:
        """Start a new run with the given user input."""
        return await self._execute(input)

    async def continue_(self, input: Optional[AgentRunInput] = None) -> AgentRunResult:
        """Continue the conversation with optional new input."""
        return await self._execute(input)

    # Alias matching TypeScript
    async def continue_run(self, input: Optional[AgentRunInput] = None) -> AgentRunResult:
        return await self._execute(input)

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self._initialize()
            self._initialized = True

    async def _initialize(self) -> None:
        """Register tools, hooks and set up plugins."""
        self._register_hooks_from_dict(self._initial_hooks)
        for tool in self._initial_tools:
            self._tools[tool.name] = tool

        for plugin in self._initial_plugins:
            ctx = AgentRuntimePluginContext(
                agent_id=self._agent_id,
                agent_role=self._agent_role,
                system_prompt=self._system_prompt,
            )
            setup = None
            if hasattr(plugin, "setup") and plugin.setup:
                result = plugin.setup(ctx)
                if asyncio.iscoroutine(result):
                    setup = await result
                else:
                    setup = result

            if setup:
                for tool in (setup.tools or []):
                    self._tools[tool.name] = tool
                if setup.hooks:
                    self._register_hooks_from_dict(
                        setup.hooks if isinstance(setup.hooks, dict) else vars(setup.hooks)
                    )

    def _register_hooks_from_dict(self, hooks: Dict[str, Any]) -> None:
        if not hooks:
            return
        if h := hooks.get("before_run") or hooks.get("beforeRun"):
            self._hooks_before_run.append(h)
        if h := hooks.get("after_run") or hooks.get("afterRun"):
            self._hooks_after_run.append(h)
        if h := hooks.get("before_model") or hooks.get("beforeModel"):
            self._hooks_before_model.append(h)
        if h := hooks.get("after_model") or hooks.get("afterModel"):
            self._hooks_after_model.append(h)
        if h := hooks.get("before_tool") or hooks.get("beforeTool"):
            self._hooks_before_tool.append(h)
        if h := hooks.get("after_tool") or hooks.get("afterTool"):
            self._hooks_after_tool.append(h)
        if h := hooks.get("on_event") or hooks.get("onEvent"):
            self._hooks_on_event.append(h)

    def _is_aborted(self) -> bool:
        return self._abort_event is not None and self._abort_event.is_set()

    def _throw_if_aborted(self) -> None:
        if self._is_aborted():
            raise self._abort_reason or AgentRuntimeAbortError("Run aborted")

    async def _emit(self, event: Dict[str, Any]) -> None:
        """Emit an event to all listeners."""
        for listener in list(self._listeners):
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass
        for hook in self._hooks_on_event:
            try:
                result = hook(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    def _apply_stop_control(self, control: Any) -> None:
        if control is None:
            return
        stop = False
        reason = None
        if isinstance(control, AgentStopControl):
            stop = control.stop
            reason = control.reason
        elif isinstance(control, dict):
            stop = control.get("stop", False)
            reason = control.get("reason")
        elif hasattr(control, "stop"):
            stop = bool(getattr(control, "stop", False))
            reason = getattr(control, "reason", None)
        if stop:
            raise ControlledStopError(reason)

    async def emit_status_notice(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Emit a status-notice event visible to event subscribers."""
        await self._emit({
            "type": "status-notice",
            "snapshot": self.snapshot(),
            "text": text,
            "metadata": metadata,
        })

    def _get_required_completion_tool_names(self) -> List[str]:
        if not self._completion_policy.get("require_completion_tool"):
            return []
        return sorted(
            name for name, tool in self._tools.items()
            if tool.lifecycle and tool.lifecycle.get("completes_run") or
               tool.lifecycle and tool.lifecycle.get("completesRun")
        )

    def _get_completion_tool_reminder(self) -> Optional[str]:
        names = self._get_required_completion_tool_names()
        if not names:
            return None
        return (
            f"[SYSTEM] This run is not complete until you call one of these terminal "
            f"completion tools: {', '.join(names)}. Continue working if requirements are not met. "
            f"If the task is complete, call the appropriate terminal completion tool now."
        )

    def _get_completion_reminder_messages(self) -> List[str]:
        msgs = []
        reminder = self._get_completion_tool_reminder()
        if reminder:
            msgs.append(reminder)
        guard = self._completion_policy.get("completion_guard")
        if callable(guard):
            result = guard()
            if result:
                msgs.append(result)
        return msgs

    async def _add_user_reminder_message(self, text: str) -> AgentMessage:
        msg = _create_message("user", [{"type": "text", "text": text}])
        self._messages.append(msg)
        await self._emit({
            "type": "message-added",
            "snapshot": self.snapshot(),
            "message": _message_to_dict(msg),
        })
        return msg

    def _find_last_assistant_message(self) -> Optional[AgentMessage]:
        for msg in reversed(self._messages):
            if msg.role == "assistant":
                return msg
        return None

    def _find_completing_tool_message(
        self,
        tool_calls: List[Dict[str, Any]],
        tool_messages: List[AgentMessage],
    ) -> Optional[AgentMessage]:
        for index, tc in enumerate(tool_calls):
            name = tc.get("toolName") or tc.get("tool_name", "")
            tool = self._tools.get(name)
            if not tool or not tool.lifecycle or tool.lifecycle.get("completesRun") is not True:
                continue
            tool_msg = tool_messages[index] if index < len(tool_messages) else None
            if tool_msg is None:
                continue
            tc_id = tc.get("toolCallId") or tc.get("tool_call_id")
            for part in tool_msg.content:
                if isinstance(part, dict) and part.get("type") == "tool-result":
                    if (part.get("toolCallId") or part.get("tool_call_id")) == tc_id:
                        if not part.get("isError") and not part.get("is_error"):
                            return tool_msg
        return None

    async def _update_usage(self, usage_delta: Dict[str, Any]) -> None:
        # Accept both snake_case (Python-native) and camelCase (TS-compatible / provider events)
        input_t = usage_delta.get("inputTokens") or usage_delta.get("input_tokens") or 0
        output_t = usage_delta.get("outputTokens") or usage_delta.get("output_tokens") or 0
        cache_r = usage_delta.get("cacheReadTokens") or usage_delta.get("cache_read_tokens") or 0
        cache_w = usage_delta.get("cacheWriteTokens") or usage_delta.get("cache_write_tokens") or 0
        cost = usage_delta.get("totalCost") or usage_delta.get("total_cost") or 0.0

        self._usage.input_tokens += int(input_t)
        self._usage.output_tokens += int(output_t)
        self._usage.cache_read_tokens += int(cache_r)
        self._usage.cache_write_tokens += int(cache_w)
        if cost:
            self._usage.total_cost = (self._usage.total_cost or 0.0) + float(cost)

        await self._emit({
            "type": "usage-updated",
            "snapshot": self.snapshot(),
            "usage": {
                "input_tokens": self._usage.input_tokens,
                "output_tokens": self._usage.output_tokens,
                "cache_read_tokens": self._usage.cache_read_tokens,
                "cache_write_tokens": self._usage.cache_write_tokens,
                "total_cost": self._usage.total_cost,
            },
        })

    async def _consume_pending_user_message(self) -> bool:
        if not self._consume_pending_user_message_fn:
            return False
        result = self._consume_pending_user_message_fn()
        if asyncio.iscoroutine(result):
            result = await result
        pending = result.strip() if isinstance(result, str) else result
        if not pending:
            return False
        msg = _create_message("user", [{"type": "text", "text": pending}])
        self._messages.append(msg)
        await self._emit({
            "type": "message-added",
            "snapshot": self.snapshot(),
            "message": _message_to_dict(msg),
        })
        return True

    async def _prepare_turn_for_request(
        self, request: AgentModelRequest
    ) -> AgentModelRequest:
        if not self._prepare_turn:
            return request
        ctx = {
            "agent_id": self._agent_id,
            "conversation_id": self._conversation_id,
            "parent_agent_id": self._parent_agent_id,
            "iteration": self._iteration,
            "messages": list(request.messages),
            "system_prompt": request.system_prompt,
            "tools": list(request.tools),
            "model": {"id": None, "provider": None},
            "signal": request.signal,
        }
        result = self._prepare_turn(ctx)
        if asyncio.iscoroutine(result):
            result = await result
        if result is None:
            return request

        new_messages = result.get("messages") if isinstance(result, dict) else getattr(result, "messages", None)
        new_system = result.get("system_prompt") if isinstance(result, dict) else getattr(result, "system_prompt", None)

        if new_messages is not None:
            prepared = clone_messages(new_messages)
            self._messages = prepared
            request = AgentModelRequest(
                messages=prepared,
                tools=request.tools,
                system_prompt=request.system_prompt,
                signal=request.signal,
                options=request.options,
            )
        if new_system is not None:
            request = AgentModelRequest(
                messages=request.messages,
                tools=request.tools,
                system_prompt=new_system,
                signal=request.signal,
                options=request.options,
            )
        return request

    async def _generate_assistant_message(
        self,
    ) -> Tuple[AgentMessage, AgentModelFinishReason]:
        """Run one LLM turn and return the assembled assistant message."""
        usage_before = _clone_usage(self._usage)

        request = AgentModelRequest(
            system_prompt=self._system_prompt,
            messages=clone_messages(self._messages),
            tools=[
                AgentToolDefinition(
                    name=t.name,
                    description=t.description,
                    input_schema=t.input_schema,
                    lifecycle=t.lifecycle,
                )
                for t in self._tools.values()
            ],
            signal=None,
            options=self._model_options,
        )

        # Consume pending user message if we're past the first iteration
        if self._iteration > 1:
            if await self._consume_pending_user_message():
                request = AgentModelRequest(
                    system_prompt=request.system_prompt,
                    messages=clone_messages(self._messages),
                    tools=request.tools,
                    signal=request.signal,
                    options=request.options,
                )

        request = await self._prepare_turn_for_request(request)

        # Run beforeModel hooks
        for hook in self._hooks_before_model:
            result = hook({"snapshot": self.snapshot(), "request": request})
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                self._apply_stop_control(result)
                _msgs = result.get("messages") if isinstance(result, dict) else getattr(result, "messages", None)
                _tools = result.get("tools") if isinstance(result, dict) else getattr(result, "tools", None)
                _opts = result.get("options") if isinstance(result, dict) else getattr(result, "options", None)
                if _msgs:
                    request = AgentModelRequest(
                        messages=clone_messages(_msgs),
                        tools=request.tools,
                        system_prompt=request.system_prompt,
                        signal=request.signal,
                        options=request.options,
                    )
                if _tools:
                    request = AgentModelRequest(
                        messages=request.messages,
                        tools=list(_tools),
                        system_prompt=request.system_prompt,
                        signal=request.signal,
                        options=request.options,
                    )
                if _opts:
                    request = AgentModelRequest(
                        messages=request.messages,
                        tools=request.tools,
                        system_prompt=request.system_prompt,
                        signal=request.signal,
                        options={**(request.options or {}), **_opts},
                    )

        # Stream from model
        stream = self._model.stream(request)
        if asyncio.iscoroutine(stream):
            stream = await stream

        content: List[Dict[str, Any]] = []
        tool_assemblies: Dict[str, Dict[str, Any]] = {}
        sequence: List[Dict[str, Any]] = []
        next_tool_index = 0
        finish_reason: AgentModelFinishReason = "stop"
        accumulated_text = ""
        accumulated_reasoning = ""

        async for event in stream:
            self._throw_if_aborted()
            etype = event.get("type", "")

            if etype == "text-delta":
                text = event.get("text", "")
                accumulated_text += text
                if sequence and sequence[-1].get("part_type") == "text":
                    sequence[-1]["text"] += text
                else:
                    sequence.append({"part_type": "text", "type": "text", "text": text})
                await self._emit({
                    "type": "assistant-text-delta",
                    "snapshot": self.snapshot(),
                    "iteration": self._iteration,
                    "text": text,
                    "accumulatedText": accumulated_text,
                })

            elif etype == "reasoning-delta":
                text = event.get("text", "")
                accumulated_reasoning += text
                if sequence and sequence[-1].get("part_type") == "reasoning":
                    sequence[-1]["text"] += text
                else:
                    sequence.append({
                        "part_type": "reasoning",
                        "type": "reasoning",
                        "text": text,
                        "redacted": event.get("redacted", False),
                    })
                await self._emit({
                    "type": "assistant-reasoning-delta",
                    "snapshot": self.snapshot(),
                    "iteration": self._iteration,
                    "text": text,
                    "accumulatedText": accumulated_reasoning,
                    "redacted": event.get("redacted"),
                })

            elif etype == "tool-call-delta":
                key = event.get("toolCallId") or f"tool_{event.get('index', next_tool_index)}"
                if event.get("toolCallId") is None and event.get("index") is None:
                    next_tool_index += 1

                if key not in tool_assemblies:
                    tool_assemblies[key] = {
                        "tool_call_id": event.get("toolCallId") or create_uid("tool"),
                        "tool_name": None,
                        "input_text": "",
                        "input_value": None,
                        "metadata": None,
                    }
                    sequence.append({"part_type": "tool", "key": key})

                asm = tool_assemblies[key]
                if event.get("toolCallId"):
                    asm["tool_call_id"] = event["toolCallId"]
                if event.get("toolName"):
                    asm["tool_name"] = event["toolName"]
                if event.get("input") is not None:
                    asm["input_value"] = event["input"]
                if event.get("inputText"):
                    asm["input_text"] = asm["input_text"] + event["inputText"]
                if event.get("metadata") is not None:
                    asm["metadata"] = _merge_tool_metadata(asm["metadata"], event["metadata"])

            elif etype == "usage":
                usage_data = event.get("usage", {})
                if usage_data:
                    await self._update_usage(usage_data)

            elif etype == "finish":
                finish_reason = event.get("reason", "stop")
                if event.get("error"):
                    self._last_error = event["error"]

        # Assemble content from sequence
        for item in sequence:
            if item.get("part_type") == "text":
                content.append({"type": "text", "text": item["text"]})
            elif item.get("part_type") == "reasoning":
                content.append({
                    "type": "reasoning",
                    "text": item["text"],
                    "redacted": item.get("redacted", False),
                })
            elif item.get("part_type") == "tool":
                key = item["key"]
                asm = tool_assemblies.get(key)
                if not asm or not asm["tool_name"]:
                    continue
                # Parse input
                parsed_input: Any = asm.get("input_value")
                if parsed_input is None and asm["input_text"]:
                    try:
                        parsed_input = json.loads(asm["input_text"])
                    except Exception:
                        parsed_input = {}
                if parsed_input is None:
                    parsed_input = {}

                content.append({
                    "type": "tool-call",
                    "toolCallId": asm["tool_call_id"],
                    "toolName": asm["tool_name"],
                    "input": parsed_input,
                    "metadata": asm.get("metadata"),
                })

        message = _create_message("assistant", content)
        metrics = _usage_delta(usage_before, self._usage)
        if metrics:
            message.metrics = metrics
        if self._message_model_info:
            message.model_info = dict(self._message_model_info)

        # afterModel hooks
        for hook in self._hooks_after_model:
            result = hook({
                "snapshot": self.snapshot(),
                "assistantMessage": _message_to_dict(message),
                "finishReason": finish_reason,
            })
            if asyncio.iscoroutine(result):
                result = await result
            self._apply_stop_control(result)

        return message, finish_reason

    async def _execute_tool_call(
        self, tool_call: Dict[str, Any]
    ) -> AgentMessage:
        """Execute a single tool call and return the result message."""
        tool_name = tool_call.get("toolName") or tool_call.get("tool_name", "")
        tool_call_id = tool_call.get("toolCallId") or tool_call.get("tool_call_id", "")
        raw_input = tool_call.get("input", {})

        tool = self._tools.get(tool_name)

        # Apply before-tool hook
        for hook in self._hooks_before_tool:
            result = hook({
                "snapshot": self.snapshot(),
                "toolCall": tool_call,
                "tool": tool,
                "input": raw_input,
            })
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                self._apply_stop_control(result)
                _skip = result.get("skip") if isinstance(result, dict) else getattr(result, "skip", False)
                _input = result.get("input") if isinstance(result, dict) else getattr(result, "input", None)
                if _skip:
                    return _create_message(
                        "tool",
                        [{
                            "type": "tool-result",
                            "toolCallId": tool_call_id,
                            "toolName": tool_name,
                            "output": "[Tool call skipped by hook]",
                            "isError": False,
                        }],
                    )
                if _input is not None:
                    raw_input = _input

        await self._emit({
            "type": "tool-started",
            "snapshot": self.snapshot(),
            "iteration": self._iteration,
            "toolCall": tool_call,
        })

        started_at = time.time()

        if tool is None:
            error_output = {"error": f"Unknown tool: {tool_name}"}
            result_msg = _create_message(
                "tool",
                [{
                    "type": "tool-result",
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                    "output": error_output,
                    "isError": True,
                }],
            )
        else:
            # Check tool approval
            if self._request_tool_approval:
                policy = self._get_tool_policy(tool_name)
                if policy and (policy.require_approval or not policy.auto_approve):
                    approval_req = ToolApprovalRequest(
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        input=raw_input,
                        agent_id=self._agent_id,
                        iteration=self._iteration,
                    )
                    approval = self._request_tool_approval(approval_req)
                    if asyncio.iscoroutine(approval):
                        approval = await approval
                    if not approval.approved:
                        output = approval.reason or f'Tool "{tool_name}" was not approved'
                        result_msg = _create_message(
                            "tool",
                            [{
                                "type": "tool-result",
                                "toolCallId": tool_call_id,
                                "toolName": tool_name,
                                "output": {"error": output},
                                "isError": True,
                            }],
                        )
                        return result_msg
                    if approval.modified_input is not None:
                        raw_input = approval.modified_input

            ctx = AgentToolContext(
                agent_id=self._agent_id,
                iteration=self._iteration,
                session_id=self._session_id,
                conversation_id=self._conversation_id,
                run_id=self._run_id,
                tool_call_id=tool_call_id,
                metadata=self._tool_context_metadata,
                snapshot=self.snapshot(),
                emit_update=lambda upd: asyncio.ensure_future(
                    self._emit({
                        "type": "tool-updated",
                        "snapshot": self.snapshot(),
                        "iteration": self._iteration,
                        "toolCall": tool_call,
                        "update": upd,
                    })
                ),
            )

            try:
                timeout = tool.timeout_ms / 1000
                coro = tool.execute(raw_input, ctx)
                if not asyncio.iscoroutine(coro):
                    output = coro
                else:
                    output = await asyncio.wait_for(coro, timeout=timeout)
                is_error = False
            except asyncio.TimeoutError:
                output = {"error": f"Tool '{tool_name}' timed out after {tool.timeout_ms}ms"}
                is_error = True
            except Exception as e:
                output = {"error": str(e)}
                is_error = True

            tool_result = AgentToolResult(output=output, is_error=is_error)

            # afterTool hook
            ended_at = time.time()
            duration_ms = int((ended_at - started_at) * 1000)
            for hook in self._hooks_after_tool:
                hook_result = hook({
                    "snapshot": self.snapshot(),
                    "tool": tool,
                    "toolCall": tool_call,
                    "input": raw_input,
                    "result": {"output": tool_result.output, "isError": tool_result.is_error},
                    "startedAt": started_at,
                    "endedAt": ended_at,
                    "durationMs": duration_ms,
                })
                if asyncio.iscoroutine(hook_result):
                    hook_result = await hook_result
                if hook_result:
                    self._apply_stop_control(hook_result)
                    _hr = hook_result.get("result") if isinstance(hook_result, dict) else getattr(hook_result, "result", None)
                    if _hr is not None:
                        if isinstance(_hr, AgentToolResult):
                            tool_result = _hr
                        elif isinstance(_hr, dict):
                            tool_result = AgentToolResult(
                                output=_hr.get("output", tool_result.output),
                                is_error=_hr.get("isError", _hr.get("is_error", tool_result.is_error)),
                            )

            result_msg = _create_message(
                "tool",
                [{
                    "type": "tool-result",
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                    "output": tool_result.output,
                    "isError": tool_result.is_error,
                }],
            )

        await self._emit({
            "type": "tool-finished",
            "snapshot": self.snapshot(),
            "iteration": self._iteration,
            "toolCall": tool_call,
            "message": _message_to_dict(result_msg),
        })
        return result_msg

    async def _execute_tool_calls(
        self, tool_calls: List[Dict[str, Any]]
    ) -> List[AgentMessage]:
        """Execute all tool calls (sequential or parallel)."""
        if self._tool_execution == "parallel":
            tasks = [self._execute_tool_call(tc) for tc in tool_calls]
            return list(await asyncio.gather(*tasks))
        else:
            results = []
            for tc in tool_calls:
                results.append(await self._execute_tool_call(tc))
            return results

    def _get_tool_policy(self, tool_name: str) -> Optional[ToolPolicy]:
        wildcard = self._tool_policies.get("*")
        specific = self._tool_policies.get(tool_name)
        if wildcard and specific:
            merged = ToolPolicy()
            merged.require_approval = specific.require_approval if specific.require_approval is not None else wildcard.require_approval
            merged.auto_approve = specific.auto_approve if specific.auto_approve is not None else wildcard.auto_approve
            return merged
        return specific or wildcard

    def _finish_run(
        self,
        status: str,
        final_message: Optional[AgentMessage],
        output_override: Optional[str] = None,
    ) -> AgentRunResult:
        self._status = status
        text = output_override or (text_from_message(final_message) if final_message else "")
        return AgentRunResult(
            agent_id=self._agent_id,
            agent_role=self._agent_role,
            run_id=self._run_id or create_uid("run"),
            status=status,
            iterations=self._iteration,
            output_text=text,
            messages=clone_messages(self._messages),
            usage=_clone_usage(self._usage),
        )

    async def _execute(self, inp: Optional[AgentRunInput]) -> AgentRunResult:
        await self._ensure_initialized()

        if self._status == "running":
            raise RuntimeError("Agent runtime is already running.")

        self._abort_event = asyncio.Event()
        self._abort_reason = None
        self._run_id = create_uid("run")
        self._status = "running"
        self._iteration = 0
        self._pending_tool_calls = []
        self._last_error = None
        self._usage = AgentUsage()

        try:
            # beforeRun hooks
            for hook in self._hooks_before_run:
                result = hook({"snapshot": self.snapshot()})
                if asyncio.iscoroutine(result):
                    result = await result
                self._apply_stop_control(result)

            await self._emit({"type": "run-started", "snapshot": self.snapshot()})

            if inp is not None:
                for msg in _normalize_input(inp):
                    self._messages.append(msg)
                    await self._emit({
                        "type": "message-added",
                        "snapshot": self.snapshot(),
                        "message": _message_to_dict(msg),
                    })

            # Completion tool reminder at run start
            reminder = self._get_completion_tool_reminder()
            if reminder:
                await self._add_user_reminder_message(reminder)

            final_assistant_message: Optional[AgentMessage] = None

            while self._max_iterations is None or self._iteration < self._max_iterations:
                self._throw_if_aborted()
                self._iteration += 1

                await self._emit({
                    "type": "turn-started",
                    "snapshot": self.snapshot(),
                    "iteration": self._iteration,
                })

                message, finish_reason = await self._generate_assistant_message()
                final_assistant_message = message
                self._messages.append(message)

                await self._emit({
                    "type": "message-added",
                    "snapshot": self.snapshot(),
                    "message": _message_to_dict(message),
                })
                await self._emit({
                    "type": "assistant-message",
                    "snapshot": self.snapshot(),
                    "iteration": self._iteration,
                    "message": _message_to_dict(message),
                    "finishReason": finish_reason,
                })

                if finish_reason == "aborted":
                    raise self._abort_reason or AgentRuntimeAbortError("Run aborted")

                # Find tool calls in the assistant message
                tool_calls = [
                    part for part in message.content
                    if isinstance(part, dict) and part.get("type") == "tool-call"
                ]

                if finish_reason == "error" and not tool_calls:
                    raise RuntimeError(self._last_error or "Model stream failed")

                self._pending_tool_calls = [tc.get("toolCallId", "") for tc in tool_calls]

                if not tool_calls:
                    await self._emit({
                        "type": "turn-finished",
                        "snapshot": self.snapshot(),
                        "iteration": self._iteration,
                        "toolCallCount": 0,
                    })
                    # Check completion reminders
                    completion_reminders = self._get_completion_reminder_messages()
                    if completion_reminders:
                        for rem in completion_reminders:
                            await self._add_user_reminder_message(rem)
                        continue

                    result = self._finish_run("completed", final_assistant_message)
                    for hook in self._hooks_after_run:
                        hr = hook({"snapshot": self.snapshot(), "result": result})
                        if asyncio.iscoroutine(hr):
                            await hr
                    await self._emit({
                        "type": "run-finished",
                        "snapshot": self.snapshot(),
                        "result": _run_result_to_dict(result),
                    })
                    return result

                tool_messages = await self._execute_tool_calls(tool_calls)
                self._pending_tool_calls = []

                for tool_msg in tool_messages:
                    self._messages.append(tool_msg)
                    await self._emit({
                        "type": "message-added",
                        "snapshot": self.snapshot(),
                        "message": _message_to_dict(tool_msg),
                    })

                await self._emit({
                    "type": "turn-finished",
                    "snapshot": self.snapshot(),
                    "iteration": self._iteration,
                    "toolCallCount": len(tool_calls),
                })

                # Check if a terminal tool was called
                terminal_msg = self._find_completing_tool_message(tool_calls, tool_messages)
                if terminal_msg:
                    text_override = _text_from_tool_message(terminal_msg) or None
                    result = self._finish_run("completed", final_assistant_message, text_override)
                    for hook in self._hooks_after_run:
                        hr = hook({"snapshot": self.snapshot(), "result": result})
                        if asyncio.iscoroutine(hr):
                            await hr
                    await self._emit({
                        "type": "run-finished",
                        "snapshot": self.snapshot(),
                        "result": _run_result_to_dict(result),
                    })
                    return result

            raise RuntimeError(
                f"Agent runtime exceeded maxIterations ({self._max_iterations})"
            )

        except (ControlledStopError, AgentRuntimeAbortError) as e:
            self._status = "aborted"
            self._last_error = str(e)
            result = AgentRunResult(
                agent_id=self._agent_id,
                agent_role=self._agent_role,
                run_id=self._run_id or create_uid("run"),
                status="aborted",
                iterations=self._iteration,
                output_text=text_from_message(self._find_last_assistant_message()),
                messages=clone_messages(self._messages),
                usage=_clone_usage(self._usage),
                error=e,
            )
            for hook in self._hooks_after_run:
                try:
                    hr = hook({"snapshot": self.snapshot(), "result": result})
                    if asyncio.iscoroutine(hr):
                        await hr
                except Exception:
                    pass
            await self._emit({
                "type": "run-finished",
                "snapshot": self.snapshot(),
                "result": _run_result_to_dict(result),
            })
            return result

        except Exception as e:
            self._status = "failed"
            self._last_error = str(e)
            result = AgentRunResult(
                agent_id=self._agent_id,
                agent_role=self._agent_role,
                run_id=self._run_id or create_uid("run"),
                status="failed",
                iterations=self._iteration,
                output_text=text_from_message(self._find_last_assistant_message()),
                messages=clone_messages(self._messages),
                usage=_clone_usage(self._usage),
                error=e,
            )
            for hook in self._hooks_after_run:
                try:
                    hr = hook({"snapshot": self.snapshot(), "result": result})
                    if asyncio.iscoroutine(hr):
                        await hr
                except Exception:
                    pass
            await self._emit({
                "type": "run-failed",
                "snapshot": self.snapshot(),
                "error": str(e),
            })
            return result

        finally:
            self._abort_event = None


def _message_to_dict(msg: AgentMessage) -> Dict[str, Any]:
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "createdAt": msg.created_at,
        "metadata": msg.metadata,
        "modelInfo": msg.model_info,
        "metrics": msg.metrics,
    }


def _run_result_to_dict(result: AgentRunResult) -> Dict[str, Any]:
    return {
        "agentId": result.agent_id,
        "agentRole": result.agent_role,
        "runId": result.run_id,
        "status": result.status,
        "iterations": result.iterations,
        "outputText": result.output_text,
        "messages": [_message_to_dict(m) for m in result.messages],
        "usage": {
            "inputTokens": result.usage.input_tokens,
            "outputTokens": result.usage.output_tokens,
            "cacheReadTokens": result.usage.cache_read_tokens,
            "cacheWriteTokens": result.usage.cache_write_tokens,
            "totalCost": result.usage.total_cost,
        },
        "error": str(result.error) if result.error else None,
    }


# Friendly alias
Agent = AgentRuntime


def create_agent_runtime(**kwargs: Any) -> AgentRuntime:
    """Factory function for creating an AgentRuntime."""
    return AgentRuntime(**kwargs)


def create_agent(**kwargs: Any) -> Agent:
    """Factory function for creating an Agent."""
    return Agent(**kwargs)
