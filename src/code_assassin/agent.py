"""
Agentic loop for Code Assassin: read files, search, edit, run commands,
and iterate until the task is complete.

The model emits ```tool ...``` fences (parsed by parser.py). The agent
executes them via ToolExecutor, appends results as user messages, and
re-prompts the model. Termination: no tool fences in the model's response,
or max_steps exceeded.
"""
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from .parser import Event, EventType, Parser
from .tools import ToolExecutor, MAX_RESULT_CHARS
from .editor import Editor
from .context import ContextManager
from .ollama import OllamaClient
from .session import Session
from .ui import UI
from .router import Router
from .tts import TTS


class AgentStatus(Enum):
    RUNNING = "running"
    FINISHED = "finished"
    STEP_CAP = "step_cap"
    ABORTED = "aborted"


@dataclass
class AgentResult:
    status: AgentStatus
    final_detail: str = ""
    final_speak: str = ""


class Agent:
    """Runs an agentic loop: model -> tool execution -> re-prompt until done."""

    def __init__(
        self,
        config,
        context: ContextManager,
        ollama: OllamaClient,
        editor: Editor,
        session: Session,
        ui: UI,
        router: Router,
        tool_executor: ToolExecutor,
        tts=None,
    ):
        self.config = config
        self.context = context
        self.ollama = ollama
        self.editor = editor
        self.session = session
        self.ui = ui
        self.router = router
        self.tool_executor = tool_executor
        self.tts = tts
        self.max_steps = config.max_steps

    async def run(self, user_input: str) -> AgentResult:
        """Execute the agentic loop for one user prompt.

        The caller is responsible for recording the user turn in the session
        (cli.start / cli.one_shot) before calling run(), so the prompt is not
        duplicated.
        """
        steps = 0
        corrected = False
        edited = False

        # Persistent accumulators across loop iterations
        final_prose: List[str] = []
        final_spoke = ""
        final_spoke_flag = False

        while steps < self.max_steps:
            # Build prompt: system + session turns + injected context + current request
            messages = self.context.build_prompt(user_input, self.session)

            # Stream Ollama response through parser, collecting events
            parser = Parser()
            prose_parts: List[str] = []
            tool_events: List[Event] = []
            warning_parts: List[str] = []
            spoke_flag = False
            spoke_content = ""

            chat_call = self.ollama.chat(
                model=self.config.model,
                messages=messages,
                num_ctx=self.config.num_ctx,
                num_predict=self.config.num_predict,
                temperature=self.config.temperature,
            )
            chunks: List[str] = []
            if hasattr(chat_call, "__aiter__"):
                async for chunk in chat_call:
                    chunks.append(chunk)
            else:
                result = await chat_call
                chunks = [result] if isinstance(result, str) else list(result)

            for chunk in chunks:
                events = parser.feed(chunk)
                for ev in events:
                    if ev.type == EventType.SPEAK:
                        spoke_flag = True
                        spoke_content = ev.content
                    elif ev.type == EventType.PROSE:
                        prose_parts.append(ev.content)
                        self.ui.print_prose(ev.content)
                    elif ev.type == EventType.CODE_BLOCK:
                        # Apply edit immediately (backed + undoable). A fence
                        # without file= is print-only: render it, never write it.
                        if not ev.path:
                            self.ui.print_code(ev.content, ev.language)
                        else:
                            ok, apply_msg = self.editor.apply_with_result(ev)
                            if not ok:
                                warning_parts.append(f"edit: {apply_msg}")
                            else:
                                edited = True
                    elif ev.type == EventType.TOOL:
                        tool_events.append(ev)
                    elif ev.type == EventType.WARNING:
                        warning_parts.append(ev.content)

            # Flush any remaining buffered events
            for ev in parser.flush():
                if ev.type == EventType.SPEAK:
                    spoke_flag = True
                    spoke_content = ev.content
                elif ev.type == EventType.PROSE:
                    prose_parts.append(ev.content)
                    self.ui.print_prose(ev.content)
                elif ev.type == EventType.CODE_BLOCK:
                    if not ev.path:
                        self.ui.print_code(ev.content, ev.language)
                    else:
                        ok, apply_msg = self.editor.apply_with_result(ev)
                        if not ok:
                            warning_parts.append(f"edit: {apply_msg}")
                        else:
                            edited = True
                elif ev.type == EventType.TOOL:
                    tool_events.append(ev)
                elif ev.type == EventType.WARNING:
                    warning_parts.append(ev.content)

            # Accumulate into persistent storage for step-cap fallback
            final_prose.extend(prose_parts)
            if spoke_flag:
                final_spoke = spoke_content.strip()
                final_spoke_flag = True

            self.ui.flush_prose()

            # Render warnings
            for w in warning_parts:
                self.ui.print_warning(w)

            # --- Decision: were there tool requests? ---
            if not tool_events:
                raw_detail = "".join(prose_parts).strip()

                # Guard: small models often narrate instead of acting. If the
                # user asked for an action and the model returned no tool fence
                # and no code fence, re-prompt once with an explicit correction
                # instead of accepting a fabricated "done".
                if (
                    not corrected
                    and not edited
                    and "```" not in raw_detail
                    and self._looks_like_action(user_input)
                ):
                    corrected = True
                    if raw_detail:
                        self.session.add_turn("assistant", raw_detail)
                    self.session.add_turn(
                        "user",
                        "[correction] You emitted no tool fence, so nothing was done. "
                        "Do the work now: emit a ```tool fence (or a ```diff file=... "
                        "fence for edits). Do not describe the work. Emit the fence.",
                    )
                    self.ui.print_status("no tool call detected; asking model to act")
                    steps += 1
                    continue

                # --- FINAL ANSWER ---
                clean_detail = self._extract_detail(raw_detail)

                # Speak final answer — use <speak> if the model gave it,
                # otherwise fall back to a concise excerpt from the detail.
                speak_text = ""
                if spoke_flag:
                    speak_text = spoke_content.strip()
                elif clean_detail:
                    # Fallback: summarize the final detail into ≤40 words
                    words = clean_detail.split()
                    speak_text = " ".join(words[:40])

                # Save session turn (clean detail only, per existing protocol)
                self.session.add_turn("assistant", clean_detail)

                # Speak final answer
                if speak_text and self.tts is not None:
                    self.tts.speak(speak_text)

                return AgentResult(
                    status=AgentStatus.FINISHED,
                    final_detail=clean_detail,
                    final_speak=speak_text,
                )

            # --- INTERMEDIATE STEP: execute tool requests ---
            result_messages: List[str] = []
            for te in tool_events:
                ok, error_msg, result = self.tool_executor.execute(te)

                # Render status line in UI
                if ok:
                    path_disp = te.tool_path or "?"
                    self.ui.print_tool(f"{te.tool_type} {path_disp}")
                else:
                    self.ui.print_warning(error_msg)

                # Format result message to feed back to the model
                result_trunc = (
                    self.tool_executor._truncate(result)
                    if isinstance(result, str)
                    else str(result)[:MAX_RESULT_CHARS]
                )
                if ok and result:
                    result_msg = (
                        f"[tool result for {te.tool_type} {te.tool_path or '?'}]\n"
                        f"{result_trunc}"
                    )
                elif ok:
                    result_msg = (
                        f"[tool result for {te.tool_type} {te.tool_path or '?'}]\n"
                        "<completed>"
                    )
                else:
                    result_msg = (
                        f"[tool error for {te.tool_type} {te.tool_path or '?'}]\n"
                        f"{error_msg}"
                    )

                result_messages.append(result_msg)

            # Append each result as a user message so the model sees them next turn
            for rm in result_messages:
                self.session.add_turn("user", rm)

            steps += 1

        # Step cap hit
        raw_detail = "".join(final_prose).strip()
        clean_detail = self._extract_detail(raw_detail)
        self.session.add_turn("assistant", clean_detail)
        self.ui.print_status("max steps reached, finishing")
        if final_spoke_flag and self.tts is not None:
            self.tts.speak(final_spoke)
        return AgentResult(
            status=AgentStatus.STEP_CAP,
            final_detail=clean_detail,
        )

    _ACTION_VERBS = frozenset({
        "add", "create", "implement", "fix", "change", "update", "remove",
        "delete", "refactor", "rename", "run", "read", "list", "search",
        "find", "grep", "show", "write", "edit", "make", "build", "test",
        "install", "move", "copy", "commit", "push", "revert", "apply",
    })

    @classmethod
    def _looks_like_action(cls, text: str) -> bool:
        """Heuristic: does this request ask the agent to do something?"""
        import re

        words = re.findall(r"[a-zA-Z]+", text.lower())[:4]
        return any(w in cls._ACTION_VERBS for w in words)

    @staticmethod
    def _extract_detail(raw: str) -> str:
        """Extract the clean <detail> content from raw model response."""
        import re

        m = re.search(r"<detail>(.*?)</detail>", raw, re.DOTALL)
        if m:
            return m.group(1).strip()
        # If no <detail> tag, strip <speak> only and return the rest
        m2 = re.search(r"<speak>(.*?)</speak>", raw, re.DOTALL)
        if m2:
            return raw.replace(m2.group(0), "").strip()
        return raw.strip()
