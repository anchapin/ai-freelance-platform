# Implementation Plan

[Overview]
Create a modern, quick startup command for ArbitrageAI that allows developers to start all required services (Ollama, FastAPI backend, Vite frontend) with a single command, following February 2026 best practices for Python/Node.js hybrid projects.

The current startup process requires developers to manually run multiple commands across 3-4 terminal windows. This implementation will streamline that into a single command using a Justfile, which is the modern standard for project task runners in 2026, replacing older Makefile approaches due to its simpler syntax and cross-platform support.

[Types]
This implementation modifies the project's configuration and adds a new task runner file:

- **New File**: `justfile` - A modern command runner (just.systems) that provides simple, fast startup commands
- **Modified File**: `pyproject.toml` - Add console script entry point for `arbitrage-ai` command
- **New File**: `scripts/arbitrage-ai` - Optional shell wrapper for direct execution

[Files]
Single sentence describing file modifications.

Detailed breakdown:
- **New files to be created:**
  - `justfile` - Main task runner with startup commands (root directory)
  - `scripts/arbitrage-ai` - Optional shell script wrapper (executable)
  
- **Existing files to be modified:**
  - `pyproject.toml` - Add `[project.scripts]` section for console entry point
  
- **Files to consider (optional):**
  - `README.md` - Update startup instructions to mention the new command
  - `CLAUDE.md` - Add the new startup command to development commands section

[Functions]
Single sentence describing function modifications.

This implementation adds new command definitions rather than modifying existing functions:

- **New commands (in justfile):**
  - `just` or `just start` - Starts all services (Ollama, Backend, Frontend) with proper environment setup
  - `just backend` - Starts only the FastAPI backend
  - `just frontend` - Starts only the Vite frontend
  - `just ollama` - Starts only Ollama with P40 optimizations
  - `just install` - Installs all dependencies (Python and Node.js)
  - `just setup` - Full first-time setup (dependencies + Docker image)
  - `just stop` - Stops all running services
  - `just status` - Shows status of all services
  
- **New console script (pyproject.toml):**
  - `arbitrage-ai` - CLI command to start the application (runs `just start`)

[Classes]
Single sentence describing class modifications.

This implementation does not modify any classes - it's purely a configuration and script addition.

[Dependencies]
Single sentence describing dependency modifications.

Details of new packages, version changes, and integration requirements:
- **Just** (command runner) - Install via: `curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash` or `brew install just`
- **No Python package changes** - Uses existing uvicorn and npm already in project
- **Optional**: Add `entr` for file-watching automation (if desired)

[Testing]
Single sentence describing testing approach.

Test file requirements, existing test modifications, and validation strategies:
- Test that `just` command is available in the system
- Test that `just start` launches all three services successfully
- Test that ports 8000 (backend) and 5173 (frontend) are accessible
- Test that the application loads at http://localhost:5173
- Verify no conflicts with existing services on the system

[Implementation Order]
Single sentence describing the implementation sequence.

Numbered steps showing the logical order of changes to minimize conflicts and ensure successful integration:

1. **Create the justfile** - Define all startup commands with proper environment variables and service management
2. **Update pyproject.toml** - Add console script entry point for `arbitrage-ai` command
3. **Create shell wrapper script** - Optional executable script in scripts/ directory
4. **Update documentation** - Add new commands to README.md and CLAUDE.md
5. **Test the implementation** - Verify all services start correctly with single command

