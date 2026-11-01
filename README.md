# Code Assassin

## Overview

Terminal voice-driven coding assistant powered by local Qwen 2.5 Coder 3B and Piper TTS.

## Features

- **Keyboard input only** — no microphone or STT in v1
- **GPU LLM** — Ollama `qwen2.5-coder:3b` (4 GB VRAM target)
- **CPU TTS** — Piper voice `en_GB-alan-medium` (zero VRAM)
- **Dual output** — Markdown/code to terminal, short voice summary to speakers
- **Autonomous editing** — model-proposed changes with safety checks
- **Per-project memory** — Persistent conversation history
- **Package management** — Python 3.11+ with `uv`

## Architecture

```mermaid
graph TD
    A[stdin / prompt_toolkit] --> B[CLI controller]
    B --> C[context builder]
    C --> D[Ollama /api/chat (GPU)]
    D --> E[streaming token parser]
    E --> F[<speak> queue] --> G[Piper worker (CPU)]
    E --> H[<detail> stream] --> I[Rich terminal]
    I --> J[editor + backups]
    B --> K[.code-assassin/memory_<task>.json]
```

## Quickstart

### Windows

```powershell
# Clone and setup
cd D:\Projects
uv clone https://github.com/Kilo-Org/Code-Assassin Code-Assassin
cd Code-Assassin

# Setup with default values
powershell scripts\setup.ps1

# Or setup with custom options
powershell scripts\setup.ps1 -ProjectName "qwen2.5-coder:3b" -Voice "en_GB-alan-medium"
```

### Unix/macOS

```bash
cd D:/Projects
uv clone https://github.com/Kilo-Org/Code-Assassin Code-Assassin
cd Code-Assassin

# Setup with default values
./scripts/setup.sh

# Or setup with custom options
./scripts/setup.sh qwen2.5-coder:3b en_GB-alan-medium
```

### Manual Installation

```bash
# Create directory
mkdir -p D:/Projects/Code-Assassin
cd D:/Projects/Code-Assassin

# Initialize git repository
git init -b main

# Initialize uv project
uv init --python 3.11
cat > pyproject.toml << 'EOF'
[tool.uv]
dependencies = [
    "typer[all]>=0.12",
    "rich>=13.0",
    "prompt-toolkit>=3.0",
    "httpx>=0.27",
    "sounddevice>=0.4",
    "numpy>=1.24",
    "piper-tts>=1.1",
]

[project.scripts]
assassin = "code_assassin.cli:app"
EOF

uv sync
```

## Usage

### Interactive Session

```bash
assassin
```

Or with custom options:

```bash
assassin --task myproject --file src/code_assassin/parser.py --no-voice
assassin --task myproject --diff
assassin --task myproject --staged
```

### One-Shot Questions

```bash
assassin ask "Summarize this project"
assassin ask "Explain the parser" --file src/code_assassin/parser.py
assassin ask "Refactor this code" --allow-overwrite
```

### Voice Control

```bash
assassin --task myproject --voice on
assassin --task myproject --voice off
```

### Edits Control

```bash
assassin --task myproject --no-edit
assassin --task myproject --edits on
assassin --task myproject --allow-overwrite
```

### Slash Commands (in interactive session)

- `/help` - Show help
- `/task myproject` - Switch task
- `/tasks` - List available tasks
- `/new` - Start new task
- `/diff` - Include git diff
- `/file src/test.py` - Include file
- `/edits on|off` - Enable/disable auto-editing
- `/voice on|off` - Enable/disable voice
- `/overwrite` - Enable overwrite mode
- `/undo` - Undo last edit
- `/clear` - Clear conversation
- `/quit` - Exit

### System Checks

```bash
assassin doctor
```

Checks Ollama reachability, model presence, voice files, audio device, and write access.

### Benchmarking

```bash
assassin bench
```

Measures first token latency, tokens per second, and VRAM usage.

### Voice Management

```bash
assassin voices list
assassin voices download en_GB-alan-medium
```

## Technical Details

### Input Protocol

Keyboard input → CLI controller → context builder → Ollama → streaming parser → router

### Output Protocol

Model output must contain:

```text
<speak>One or two sentences. Verdict and next action. No code, no markdown. Max 40 words.</speak>
<detail>
Full Markdown answer. Code fences as needed.
</detail>
```

### Edit Rules

- **Edit existing file**: ` ```diff file=relative/path.py ` with unified diff
- **Create new file**: ` ```python file=relative/path.py ` with full contents
- **Print-only snippet**: no `file=` attribute
- **Missing/malformed file=** means print only; never write

### Safety

- Project-root confinement
- Backup + undo for all edits
- Secret filtering (`.env*`, keys)
- Size limits (256 KB per file)
- No shell execution

### Context Management

- 2,048 token budget
- System prompt + latest 6 turns
- Targeted file/diff injection via `@file`, `--file`, `--diff`

### Voice Pipeline

- Long-lived Piper worker
- Sentence splitting for low latency (~500ms target)
- Raw PCM via `sounddevice`
- Lazy imports for CI compatibility

## Configuration

### assassin.toml

```toml
[general]
model = "qwen2.5-coder:3b"
ollama_url = "http://127.0.0.1:11434"
num_ctx = 2048
num_predict = 512
temperature = 0.2
voice = "en_GB-alan-medium"
voice_dir = ".tools/voices"
speak = true
edits = true
max_turns = 6
```

### Modelfile

Create `Modelfile` in project root for Ollama preset:

```
FROM qwen2.5-coder:3b
PARAMETER num_ctx 2048
PARAMETER num_predict 512
PARAMETER temperature 0.2
```

## System Requirements

### Hardware

- **CPU**: Modern x86-64 processor (Intel i5 equivalent or better)
- **RAM**: At least 4 GB (16 GB+ recommended)
- **VRAM**: 4 GB for LLM inference
- **Audio**: Sound device with CPU support for TTS

### Software

- **Python 3.11+**
- **uv** package manager
- **Ollama** for LLM inference
- **Piper TTS** for voice synthesis

### Recommended Environment

```bash
# Ubuntu/Debian
apt update
apt install -y python3.11-venv python3-pip
pip install uv

# Install system dependencies for audio
apt install -y portaudio19-dev

# Clone and setup
uv clone https://github.com/Kilo-Org/Code-Assassin
cd Code-Assassin
./scripts/setup.sh
```

## Testing

### Unit Tests

```bash
uv run pytest -q
```

### Linting

```bash
uv run ruff check .
```

### Integration Tests (require Ollama/Piper)

```bash
CODE_ASSASSIN_INTEGRATION=1 uv run pytest tests/test_integration.py -v
```

## Development

### Project Structure

```
D:\Projects\Code-Assassin\
  pyproject.toml
  uv.lock
  README.md
  LICENSE
  assassin.toml              # Optional committed project config
  Modelfile                  # Optional Ollama preset
  prompts/
    system.md               # System prompt
  src/code_assassin/         # Core application
    __init__.py
    __main__.py
    cli.py                   # Typer commands + interactive loop
    config.py                # Defaults, env, TOML, CLI precedence
    ollama.py                # Streaming /api/chat client
    parser.py                # <speak>/<detail> + fence state machine
    router.py                # speech queue, code/diff events, warnings
    ui.py                    # Rich rendering, status, diff colors
    tts.py                   # worker lifecycle, sentence splitting, queue
    tts_worker.py            # long-lived Piper subprocess
    audio.py                 # sounddevice raw output
    session.py               # memory_<task>.json load/save/trim
    context.py               # @file, --file, --diff, token budget
    editor.py                # marked-fence validation/apply
    backup.py                # backup transactions + undo
    doctor.py                # environment checks
    voices.py                # voice download/list
    bench.py                 # latency + VRAM benchmark
  tests/                   # Unit tests
    test_parser.py
    test_router.py
    test_session.py
    test_context.py
    test_editor.py
    test_backup.py
    test_cli.py
    test_integration.py     # Opt-in
  scripts/                 # Setup scripts
    setup.ps1
    setup.sh
  .github/workflows/      # CI/CD
    ci.yml
```

## Roadmap

### v1.0

- ✅ Terminal voice assistant
- ✅ Ollama integration
- ✅ Piper TTS
- ✅ Auto-editing with safety
- ✅ Session memory
- ✅ Context management
- ✅ Basic CLI

### v1.1

- [ ] Multi-language support
- [ ] Custom voice management
- [ ] Advanced context merging
- [ ] Better error recovery

### v1.2

- [ ] Web dashboard
- [ ] IDE integration
- [ ] Advanced TTS features

## Limitations

- **No STT**: Requires keyboard input
- **4 GB VRAM limit**: Sufficient for 3B models
- **No shell execution**: For security
- **Audio required**: Need audio device for voice output
- **Piper dependency**: Requires ONNX runtime

## License

MIT License. See LICENSE file.

## Credits

Inspired by Project Silas Core. Used only as inspiration for voice/terminal concepts.

## Support

For issues and questions, visit the repository.

---

*Note: This project requires local hardware and may have specific audio requirements. Ensure your system has the necessary drivers and permissions.*