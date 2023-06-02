"""Callback Handler that prints to streamlit."""

from __future__ import annotations

from enum import Enum
from typing import Any, NamedTuple

from langchain.callbacks.base import BaseCallbackHandler
from langchain.schema import AgentAction, AgentFinish, LLMResult
from streamlit.delta_generator import DeltaGenerator

from mutable_expander import MutableExpander


def _convert_newlines(text: str) -> str:
    """Convert newline characters to markdown newline sequences (space, space, newline)"""
    return text.replace("\n", "  \n")


CHECKMARK_EMOJI = "✅"
THINKING_EMOJI = ":thinking_face:"


class LLMThoughtState(Enum):
    # The LLM is thinking about what to do next. We don't know which tool we'll run.
    THINKING = "THINKING"
    # The LLM has decided to run a tool. We don't have results from the tool yet.
    RUNNING_TOOL = "RUNNING_TOOL"
    # We have results from the tool.
    COMPLETE = "COMPLETE"


class ToolRecord(NamedTuple):
    name: str
    input_str: str


class LLMThought:
    def __init__(self, parent_container: DeltaGenerator, expanded: bool):
        self._container = MutableExpander(
            parent_container=parent_container,
            label=f"{THINKING_EMOJI} **Thinking...**",
            expanded=expanded,
        )
        self._state = LLMThoughtState.THINKING
        self._llm_token_stream = ""
        self._llm_token_writer_idx: int | None = None
        self._last_tool: ToolRecord | None = None

    @property
    def last_tool(self) -> ToolRecord | None:
        """The last tool executed by this thought"""
        return self._last_tool

    def _reset_llm_token_stream(self) -> None:
        self._llm_token_stream = ""
        self._llm_token_writer_idx = None

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str]) -> None:
        self._reset_llm_token_stream()

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        # This is only called when the LLM is initialized with `streaming=True`
        self._llm_token_stream += _convert_newlines(token)
        self._llm_token_writer_idx = self._container.markdown(
            self._llm_token_stream, index=self._llm_token_writer_idx
        )

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        # `response` is the concatenation of all the tokens received by the LLM.
        # If we're receiving streaming tokens from `on_llm_new_token`, this response
        # data is redundant
        self._reset_llm_token_stream()

    def on_llm_error(self, error: Exception | KeyboardInterrupt, **kwargs: Any) -> None:
        self._container.markdown("**LLM encountered an error...**")
        self._container.exception(error)

    def on_tool_start(
        self, serialized: dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        # Called with the name of the tool we're about to run (in `serialized[name]`),
        # and its input. We don't output this, because it's redundant: the LLM will
        # have just printed the name of the tool and its input before calling the tool.
        self._state = LLMThoughtState.RUNNING_TOOL
        tool_name = serialized["name"]
        self._last_tool = ToolRecord(name=tool_name, input_str=input_str)
        self._container.update(
            new_label=self._get_tool_label(THINKING_EMOJI, self._last_tool)
        )

    def on_tool_end(
        self,
        output: str,
        color: str | None = None,
        observation_prefix: str | None = None,
        llm_prefix: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._container.markdown(f"**{output}**")

    def on_tool_error(
        self, error: Exception | KeyboardInterrupt, **kwargs: Any
    ) -> None:
        self._container.markdown("**Tool encountered an error...**")
        self._container.exception(error)

    def on_agent_action(
        self, action: AgentAction, color: str | None = None, **kwargs: Any
    ) -> Any:
        # Called when we're about to kick off a new tool. The `action` data
        # tells us the tool we're about to use, and the input we'll give it.
        # We don't output anything here, because we'll receive this same data
        # when `on_tool_start` is called immediately after.
        pass

    def finish(self, final_label: str | None = None) -> None:
        """Finish the thought."""
        if final_label is None and self._state == LLMThoughtState.RUNNING_TOOL:
            final_label = self._get_tool_label(CHECKMARK_EMOJI, self._last_tool)
        self._state = LLMThoughtState.COMPLETE
        self._container.update(new_label=final_label)

    def clear(self) -> None:
        """Remove the thought from the screen. A cleared thought can't be reused."""
        self._container.clear()

    @staticmethod
    def _get_tool_label(emoji: str, tool: ToolRecord) -> str:
        return f"{emoji} **{tool.name}**"


class StreamlitCallbackHandler(BaseCallbackHandler):
    def __init__(self, container: DeltaGenerator, expand_new_thoughts: bool = True):
        """Initialize callback handler."""
        self._container = container
        self._current_thought: LLMThought | None = None
        self._completed_thoughts: list[LLMThought] = []
        self._expand_new_thoughts = expand_new_thoughts

    def _require_current_thought(self) -> LLMThought:
        if self._current_thought is None:
            raise RuntimeError("Current LLMThought is unexpectedly None!")
        return self._current_thought

    def _get_last_thought(self) -> LLMThought | None:
        """Get the most recent completed thought if we have one."""
        if len(self._completed_thoughts) > 0:
            return self._completed_thoughts[len(self._completed_thoughts) - 1]
        return None

    def on_llm_start(
        self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any
    ) -> None:
        if self._current_thought is None:
            self._current_thought = LLMThought(
                self._container, self._expand_new_thoughts
            )
        self._current_thought.on_llm_start(serialized, prompts)

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        self._require_current_thought().on_llm_new_token(token, **kwargs)

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        self._require_current_thought().on_llm_end(response, **kwargs)

    def on_llm_error(self, error: Exception | KeyboardInterrupt, **kwargs: Any) -> None:
        self._require_current_thought().on_llm_error(error, **kwargs)

    def on_tool_start(
        self, serialized: dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        tool_name = serialized["name"]

        # If our last thought involved this same tool, "reopen" that last thought
        last_thought = self._get_last_thought()
        if (
            last_thought is not None
            and last_thought.last_tool is not None
            and last_thought.last_tool.name == tool_name
        ):
            cur_thought = self._require_current_thought()
            # append cur_thought's records to last_thought
            cur_thought.clear()
            self._current_thought = last_thought
            self._completed_thoughts.pop()

        self._require_current_thought().on_tool_start(serialized, input_str, **kwargs)

    def on_tool_end(
        self,
        output: str,
        color: str | None = None,
        observation_prefix: str | None = None,
        llm_prefix: str | None = None,
        **kwargs: Any,
    ) -> None:
        thought = self._require_current_thought()
        thought.on_tool_end(output, color, observation_prefix, llm_prefix, **kwargs)
        thought.finish()

        self._completed_thoughts.append(thought)
        self._current_thought = None

    def on_tool_error(
        self, error: Exception | KeyboardInterrupt, **kwargs: Any
    ) -> None:
        self._require_current_thought().on_tool_error(error, **kwargs)

    def on_text(
        self,
        text: str,
        color: str | None = None,
        end: str = "",
        **kwargs: Any,
    ) -> None:
        pass

    def on_chain_start(
        self, serialized: dict[str, Any], inputs: dict[str, Any], **kwargs: Any
    ) -> None:
        # chain is redundant with tool + LLM
        pass

    def on_chain_end(self, outputs: dict[str, Any], **kwargs: Any) -> None:
        # chain is redundant with tool + LLM
        pass

    def on_chain_error(
        self, error: Exception | KeyboardInterrupt, **kwargs: Any
    ) -> None:
        # chain is redundant with tool + LLM
        pass

    def on_agent_action(
        self, action: AgentAction, color: str | None = None, **kwargs: Any
    ) -> Any:
        self._require_current_thought().on_agent_action(action, color, **kwargs)

    def on_agent_finish(
        self, finish: AgentFinish, color: str | None = None, **kwargs: Any
    ) -> None:
        if self._current_thought is not None:
            self._current_thought.finish(f"{CHECKMARK_EMOJI} **Complete!**")
            self._current_thought = None

        if "output" in finish.return_values:
            self._container.markdown(finish.return_values["output"])
        else:
            self._container.write(finish.return_values)
