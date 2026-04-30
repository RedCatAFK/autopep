# Autopep2 Terminal Agent

Standalone OpenAI Agents SDK terminal chatbot for protein research and design
workflows. It uses `gpt-5.5`, keeps conversation state in SQLite, and writes
all generated files under `autopep2/sandbox`.

Each CLI start creates a fresh active sandbox at
`autopep2/sandbox/runs/<utc_timestamp>_<id>`. Tool calls, generated files, and
the SQLite conversation database for that process live inside that run folder,
so killing and restarting the CLI starts cleanly.

Agent runs have no practical turn cap by default. Set
`AUTOPEP2_MAX_AGENT_TURNS` to a positive integer if you want to re-enable one.

## Setup

```bash
cd autopep2
uv sync
```

Populate `autopep2/.env` with at least `OPENAI_API_KEY`. Add Modal API keys for
Proteina, Chai, interaction scoring, and quality scoring before using those
tools.

## Run

```bash
uv run python main.py
```

DeepSeek V4 Pro through Fireworks AI:

```bash
uv run python main.py --deepseek
```

Tree-search agent with the same Fireworks DeepSeek backend:

```bash
uv run python tree.py --deepseek
```

One-shot mode:

```bash
uv run python main.py --prompt "search PMC for BACE1 binder literature"
```

REPL commands:

- `:reset` clears the SQLite conversation session.
- `:exit` exits.

## Tool Surface

- `execute_bash`: runs bash from the active run sandbox, default timeout 120s.
- `execute_python`: writes and runs a Python script under the active run sandbox.
- `literature_search`: searches NCBI PMC via E-Utilities.
- `search_pdb`: searches RCSB PDB and saves compact metadata.
- `fetch_pdb`: downloads `.pdb` or `.cif` structures into the active run sandbox.
- `run_proteina`: calls the Proteina-Complexa Modal `/design` endpoint.
- `run_chai`: calls the Chai-1 Modal `/predict` endpoint.
- `run_scorers`: calls interaction and quality scorer Modal endpoints in parallel.

This is a directory sandbox, not an OS-level chroot. Tool instructions and path
arguments keep agent-created files under the current
`autopep2/sandbox/runs/<run_id>` folder.
