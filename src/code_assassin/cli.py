import argparse

def status():
    print(f"Task: {task}")
    print(f"Model: {model}")
    print(f"Agent on: {agent_on}")
    print(f"Editor on: {editor_on}")
    print(f"Voice on: {voice_on}")
    print(f"Turns: {turns}")
"""
CLI interface with interactive loop and commands.
"""
import asyncio
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from .router import Router
from .ui import UI
from .config import Config
from .session import Session
from .context import ContextManager
from .ollama import OllamaClient
from .editor import Editor
from .tts import TTS
from .parser import Parser, EventType, Event
from .tools import ToolExecutor
from .agent import Agent


def _extract_detail(response: str) -> str:
    """Extract the clean <detail> content from a raw model response.

    Falls back to the whole response if no <detail> tag is present.
    """
    import re
    m = re.search(r"<detail>(.*?)</detail>", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Strip <speak> only (keeps plain text)
    m2 = re.search(r"<speak>(.*?)</speak>", response, re.DOTALL)
    if m2:
        return response.replace(m2.group(0), "").strip()
    return response.strip()


class AssassinApp:
    """Main CLI application."""

    def __init__(self):
        self.config = Config.load()
        self.ui = UI()
        self.router = Router()
        self.session: Optional[Session] = None
        self.context = ContextManager(self.config)
        self.ollama = OllamaClient(self.config.ollama_url)
        self.editor = Editor(root=self.config.root)
        self.tts = TTS(voice=self.config.voice, voice_dir=self.config.voice_dir)
        self.running = False
        self.current_task = "default"
        self._prompt_session = None

        # Agentic mode flags (overridden by CLI options)
        self.no_agent = False
        self.no_run = False
        self.allow_run = False

        # Setup routes
        self.router.on_speak = self.tts.speak
        self.router.on_prose = self.ui.print_prose
        self.router.on_code_block = self._on_code_block
        self.router.on_warning = self.ui.print_warning
        self.router.on_tool = self.ui.print_tool

        if not self.config.speak:
            self.tts.disable()
        if not self.config.edits:
            self.editor.disable()

        self.editor.set_overwrite_mode(False)

        # Lazily created when agent mode is first used
        self._tool_executor: Optional[ToolExecutor] = None
        self._agent: Optional[Agent] = None

    def _on_code_block(self, event: Event) -> None:
        """Handle a code block from the agent: print-only, never write."""
        if event.path is None:
            self.ui.print_code(event.content, event.language)
        else:
            ok, apply_msg = self.editor.apply_with_result(event)
            if not ok:
                warning_parts.append(f"edit: {apply_msg}")

    def _get_tool_executor(self) -> ToolExecutor:
        """Lazily create ToolExecutor + Agent wired together."""
        if self._tool_executor is None:
            self._tool_executor = ToolExecutor(
                project_root=Path.cwd(),
                editor=self.editor,
                ui=self.ui,
                config=self.config,
                tool_log_callback=self._tool_log_callback,
            )
            self._agent = Agent(
                config=self.config,
                context=self.context,
                ollama=self.ollama,
                editor=self.editor,
                session=self.session,
                ui=self.ui,
                router=self.router,
                tool_executor=self._tool_executor,
                tts=self.tts,
            )
        return self._tool_executor

    def _get_agent(self) -> Agent:
        """Get the Agent instance, lazily initializing if needed."""
        self._get_tool_executor()
        return self._agent

    def _tool_log_callback(self, entry: dict):
        """Append a run-tool entry to the session audit log."""
        self.session.add_turn("user", f"[tool log] {entry}")

    async def start(
        self,
        task: str = "default",
        file: Optional[Path] = None,
        diff: bool = False,
        staged: bool = False,
        no_voice: bool = False,
        no_edit: bool = False,
        allow_overwrite: bool = False,
        voice: Optional[str] = None,
        edits: Optional[str] = None,
        no_agent: bool = False,
        no_run: bool = False,
        allow_run: bool = False,
    ):
        """Start the interactive session."""
        # Set agent mode flags from CLI options
        self.no_agent = no_agent
        self.no_run = no_run
        self.allow_run = allow_run
        
        self.running = True
        self.current_task = task
        self.session = Session(task).load()
        self.context.set_project_root(Path.cwd())

        if no_voice:
            self.tts.disable()
            self.tts.enabled = False
        if no_edit:
            self.editor.disable()
            self.editor.edits_enabled = False

        self.editor.set_overwrite_mode(allow_overwrite)

        if voice == "on":
            self.tts.enable()
        elif voice == "off":
            self.tts.disable()

        if edits == "on":
            self.editor.enable()
        elif edits == "off":
            self.editor.disable()

        self.tts.start()

        self.ui.print_header(f"Code Assassin - Task: {task}")
        self.ui.print_status(f"Model: {self.config.model}")
        self.ui.print_status(f"Voice: {self.config.voice}")
        self.ui.print_status(f"Edits: {'enabled' if self.editor.edits_enabled else 'disabled'}")
        self.ui.print_status(f"Agent: {'disabled' if self.no_agent else 'enabled'}")
        self.ui.print_status("Type /help for commands")

        if file:
            self.context.add_file_context(file)
        if diff or staged:
            self.context.add_diff_context(staged)

        while self.running:
            try:
                user_input = await self._get_input()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    self._handle_slash(user_input)
                    continue

                self.session.add_turn("user", user_input)
                await self._process_input(user_input)

            except (KeyboardInterrupt, EOFError, OSError):
                break
            except Exception as e:
                self.ui.print_error(f"Error: {e}")

        await self.stop()

    async def _get_input(self) -> str:
        """Get user input without blocking the running event loop."""
        try:
            from prompt_toolkit import PromptSession
            if getattr(self, "_prompt_session", None) is None:
                self._prompt_session = PromptSession()
            return await self._prompt_session.prompt_async("> ")
        except (EOFError, KeyboardInterrupt):
            raise
        except Exception:
            return await asyncio.to_thread(self.ui.print_prompt, "> ")

    def _handle_slash(self, text: str):
        """Handle slash commands."""
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "help":
            self._print_help()
        elif cmd == "task":
            if arg:
                self.current_task = arg
                self.session = Session(arg).load()
                self.ui.print_status(f"Switched to task: {arg}")
            else:
                self.ui.print_status(f"Current task: {self.current_task}")
        elif cmd == "tasks":
            self._list_tasks()
        elif cmd == "new":
            self.session = Session(self.current_task)
            self.session.delete()
            self.ui.print_status("Started new task")
        elif cmd == "diff":
            self.context.add_diff_context()
            self.ui.print_status("Git diff added to context")
        elif cmd == "file":
            if arg:
                path = Path(arg)
                self.context.add_file_context(path)
                self.ui.print_status(f"File added to context: {arg}")
            else:
                self.ui.print_error("Usage: /file <path>")
        elif cmd == "edits":
            if arg == "on":
                self.editor.enable()
                self.ui.print_status("Edits enabled")
            elif arg == "off":
                self.editor.disable()
                self.ui.print_status("Edits disabled")
            else:
                self.ui.print_error("Usage: /edits on|off")
        elif cmd == "voice":
            if arg == "on":
                self.tts.enable()
                self.ui.print_status("Voice enabled")
            elif arg == "off":
                self.tts.disable()
                self.ui.print_status("Voice disabled")
            else:
                self.ui.print_error("Usage: /voice on|off")
        elif cmd == "overwrite":
            self.editor.set_overwrite_mode(True)
            self.ui.print_status("Overwrite mode enabled")
        elif cmd == "agent":
            if arg == "on":
                self.no_agent = False
                self.ui.print_status("Agent mode enabled")
            elif arg == "off":
                self.no_agent = True
                self.ui.print_status("Agent mode disabled")
            else:
                self.ui.print_status(f"Agent: {'disabled' if self.no_agent else 'enabled'}")
        elif cmd == "run":
            if arg:
                # Run a one-off shell command with the same safety policy
                self.ui.print_status(f"Running: {arg}")
                try:
                    from .tools import ToolExecutor
                    te = ToolExecutor(
                        project_root=Path.cwd(),
                        editor=self.editor,
                        ui=self.ui,
                        config=self.config,
                    )
                    ok, error_msg, result = te.execute(type("Ev", (), {
                        "tool_type": "run",
                        "tool_cmd": arg,
                        "tool_path": "",
                        "tool_pattern": "",
                        "content": "",
                    })())
                    if ok:
                        self.ui.print_prose(result)
                    else:
                        self.ui.print_error(error_msg)
                except Exception as e:
                    self.ui.print_error(f"run failed: {e}")
            else:
                self.ui.print_error("Usage: /run <command>")
        elif cmd == "undo":
            success = self.editor.undo(self.current_task)
            self.ui.print_status("Undo last edit" if success else "No edits to undo")
        elif cmd == "clear":
            self.session.clear()
            self.ui.print_status("Conversation cleared")
        elif cmd == "quit":
            self.running = False
        else:
            self.ui.print_error(f"Unknown command: /{cmd}. Type /help")

    def _print_help(self):
        self.ui.console.print(Panel(
            "\n".join([
                "/help          - Show this help",
                "/task <name>   - Switch task",
                "/tasks         - List available tasks",
                "/new           - Start new task",
                "/diff          - Include git diff",
                "/file <path>   - Include file",
                "/edits on|off  - Enable/disable auto-editing",
                "/voice on|off  - Enable/disable voice",
                "/overwrite     - Enable overwrite mode",
                "/agent on|off  - Enable/disable agent mode",
                "/status        - Show agent status",
                "/run <command> - Run a shell command (safety policy applies)",
                "/undo          - Undo last edit",
                "/clear         - Clear conversation",
                "/quit          - Exit",
            ]),
            title="Slash Commands",
            border_style="cyan"
        ))

    def _list_tasks(self):
        """List available task memory files."""
        memory_dir = Path(".code-assassin")
        if not memory_dir.exists():
            self.ui.print_status("No tasks yet")
            return
        tasks = []
        for f in memory_dir.glob("memory_*.json"):
            task = f.stem.replace("memory_", "")
            tasks.append(task)
        if tasks:
            self.ui.print_status("Tasks: " + ", ".join(sorted(tasks)))
        else:
            self.ui.print_status("No tasks yet")

    async def _process_input(self, input_text: str):
        """Process user input and stream response through parser."""
        # If agent mode is enabled, route through the agentic loop
        if self.config.agent and not self.no_agent:
            self._get_tool_executor()  # ensures agent is wired up
            result = await self._agent.run(input_text)
            # Prose is streamed by Agent.run; do not render the detail again.
            if result.final_speak:
                # Already played via agent.run, but if TTS disabled, echo text
                if not self.config.speak:
                    self.ui.print_status(f"Assistant: {result.final_speak}")
            return

        # Original non-agent flow
        prompt = self.context.build_prompt(input_text, self.session)
        parser = Parser()
        detail_parts = []
        spoke = False

        async for chunk in self.ollama.chat(
            model=self.config.model,
            messages=prompt,
            num_ctx=self.config.num_ctx,
            num_predict=self.config.num_predict,
            temperature=self.config.temperature,
        ):
            events = parser.feed(chunk)
            for ev in events:
                if ev.type == EventType.SPEAK:
                    spoke = True
                elif ev.type == EventType.PROSE:
                    detail_parts.append(ev.content)
                self.router.route(ev)

        # Flush any remaining
        for ev in parser.flush():
            if ev.type == EventType.SPEAK:
                spoke = True
            elif ev.type == EventType.PROSE:
                detail_parts.append(ev.content)
            self.router.route(ev)

        self.ui.flush_prose()

        detail_text = "".join(detail_parts).strip()

        # Fallback: if the model didn't emit <speak>, speak the plain response
        # so the user always gets audio, not just text.
        if not spoke and detail_text:
            self.tts.speak(detail_text)

        self.session.add_turn("assistant", detail_text)

    async def stop(self):
        """Stop the application."""
        self.running = False
        self.tts.stop()
        await self.ollama.close()

    async def one_shot(
        self,
        prompt: str,
        task: str = "default",
        file: Optional[Path] = None,
        diff: bool = False,
        staged: bool = False,
        no_voice: bool = False,
        no_edit: bool = False,
        allow_overwrite: bool = False,
        voice: Optional[str] = None,
        edits: Optional[str] = None,
        no_agent: bool = False,
        no_run: bool = False,
        allow_run: bool = False,
    ) -> str:
        """Process a single prompt and return response."""
        self.no_agent = no_agent
        self.no_run = no_run
        self.allow_run = allow_run

        self.session = Session(task).load()
        self.session.add_turn("user", prompt)
        self.context.set_project_root(Path.cwd())

        if file:
            self.context.add_file_context(file)
        if diff or staged:
            self.context.add_diff_context(staged)

        if no_voice:
            self.tts.disable()
        if no_edit:
            self.editor.disable()

        self.editor.set_overwrite_mode(allow_overwrite)

        if voice == "on":
            self.tts.enable()
        elif voice == "off":
            self.tts.disable()

        if edits == "on":
            self.editor.enable()
        elif edits == "off":
            self.editor.disable()

        self.tts.start()

        # If agent mode is enabled, route through the agentic loop
        if self.config.agent and not self.no_agent:
            self._get_tool_executor()  # ensures agent is wired up
            result = await self._agent.run(prompt)
            self.tts.stop()
            await self.ollama.close()
            # Agent already rendered the detail via ui.print_prose; the
            # `ask` command prints the returned value once.
            return result.final_detail

        full_prompt = self.context.build_prompt(prompt, self.session)
        parser = Parser()
        spoke = False

        # Collect chunks from the chat call. The real Ollama client returns an
        # async generator; tests may mock it with an awaitable that returns a list.
        chat_call = self.ollama.chat(
            model=self.config.model,
            messages=full_prompt,
            num_ctx=self.config.num_ctx,
            num_predict=self.config.num_predict,
            temperature=self.config.temperature,
        )
        chunks = []
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
                    spoke = True
                self.router.route(ev)

        for ev in parser.flush():
            if ev.type == EventType.SPEAK:
                spoke = True
            self.router.route(ev)

        self.ui.flush_prose()

        # Assemble the full response from the detail prose
        full_response = "".join(chunks)

        # Fallback: if the model didn't emit <speak>, speak the plain response
        if not spoke and full_response.strip():
            self.tts.speak(full_response.strip())

        # Save only the clean detail content to session memory (strip protocol markup)
        clean_response = _extract_detail(full_response)
        self.session.add_turn("assistant", clean_response)

        # Stop TTS after one-shot
        self.tts.stop()
        await self.ollama.close()

        return full_response

    async def bench(self):
        """Run benchmark."""
        from .bench import Benchmark
        bench = Benchmark(self.config)
        results = await bench.run()
        self.ui.print_header("Benchmark Results")
        for k, v in results.items():
            self.ui.print_status(f"{k}: {v}")

    def voices_list(self):
        """List available voices."""
        from .voices import list_voices, list_local_voices
        self.ui.print_header("Curated Voices")
        for v in list_voices():
            self.ui.print_status(f"{v['name']} - {v['lang']} ({v['quality']})")
        local = list_local_voices(self.config.voice_dir)
        if local:
            self.ui.print_header("Downloaded Voices")
            for v in local:
                self.ui.print_status(v)

    def voices_download(self, voice: str):
        """Download a voice."""
        from .voices import download_voice
        self.ui.print_status(f"Downloading {voice}...")
        ok = download_voice(voice, self.config.voice_dir)
        if ok:
            self.ui.print_success(f"Downloaded {voice}")
        else:
            self.ui.print_error(f"Failed to download {voice}")


assassin_app = AssassinApp()


# Typer setup
app = typer.Typer(
    help="Terminal voice-driven coding assistant",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)


# Main callback - runs interactive session when no subcommand given
@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    task: str = typer.Option("default", "--task", help="Task name for session memory"),
    file: Optional[Path] = typer.Option(None, "--file", help="File to include as context"),
    diff: bool = typer.Option(False, "--diff", help="Include git diff as context"),
    staged: bool = typer.Option(False, "--staged", help="Include staged git diff as context"),
    no_voice: bool = typer.Option(False, "--no-voice", help="Disable TTS output"),
    no_edit: bool = typer.Option(False, "--no-edit", help="Disable auto-applying edits"),
    allow_overwrite: bool = typer.Option(False, "--allow-overwrite", help="Allow overwriting existing files"),
    voice: Optional[str] = typer.Option(None, "--voice", help="Voice control: on|off"),
    edits: Optional[str] = typer.Option(None, "--edits", help="Edits control: on|off"),
    no_agent: bool = typer.Option(False, "--no-agent", help="Disable agent mode"),
    no_run: bool = typer.Option(False, "--no-run", help="Disable shell run tool"),
    allow_run: bool = typer.Option(False, "--allow-run", help="Allow any non-blocked shell command"),
):
    """Start interactive session."""
    if ctx.invoked_subcommand is None:
        asyncio.run(assassin_app.start(
            task, file, diff, staged, no_voice, no_edit, allow_overwrite,
            voice, edits, no_agent, no_run, allow_run,
        ))


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="Prompt for the assistant"),
    task: str = typer.Option("default", "--task", help="Task name for session memory"),
    file: Optional[Path] = typer.Option(None, "--file", help="File to include as context"),
    diff: bool = typer.Option(False, "--diff", help="Include git diff as context"),
    staged: bool = typer.Option(False, "--staged", help="Include staged git diff as context"),
    no_voice: bool = typer.Option(False, "--no-voice", help="Disable TTS output"),
    no_edit: bool = typer.Option(False, "--no-edit", help="Disable auto-applying edits"),
    allow_overwrite: bool = typer.Option(False, "--allow-overwrite", help="Allow overwriting existing files"),
    voice: Optional[str] = typer.Option(None, "--voice", help="Voice control: on|off"),
    edits: Optional[str] = typer.Option(None, "--edits", help="Edits control: on|off"),
    no_agent: bool = typer.Option(False, "--no-agent", help="Disable agent mode"),
    no_run: bool = typer.Option(False, "--no-run", help="Disable shell run tool"),
    allow_run: bool = typer.Option(False, "--allow-run", help="Allow any non-blocked shell command"),
):
    """Process a single prompt and return response."""
    response = asyncio.run(assassin_app.one_shot(
        prompt, task, file, diff, staged, no_voice, no_edit, allow_overwrite,
        voice, edits, no_agent, no_run, allow_run,
    ))
    # In agent mode the detail is already streamed to the terminal by Agent.run;
    # echoing it again would print the whole answer twice.
    if not (assassin_app.config.agent and not assassin_app.no_agent):
        typer.echo(response)


@app.command()
def doctor():
    """Check system health and configuration."""
    from .doctor import Doctor
    doctor = Doctor(assassin_app.config)
    result = doctor.run_all()
    raise SystemExit(result)


@app.command()
def bench():
    """Run latency and VRAM benchmarks."""
    asyncio.run(assassin_app.bench())


# Voices subcommands
voices_app = typer.Typer(help="Voice management")
app.add_typer(voices_app, name="voices")


@voices_app.command("list")
def voices_list():
    """List available and downloaded voices."""
    assassin_app.voices_list()


@voices_app.command("download")
def voices_download(voice: str = typer.Argument(..., help="Voice name to download")):
    """Download a voice from HuggingFace."""
    assassin_app.voices_download(voice)


if __name__ == "__main__":
    app()