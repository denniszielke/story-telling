<!--
Sync Impact Report
- Version change: 0.0.0 → 1.0.0 (major – first concrete constitution, replaces template placeholders)
- Modified principles:
	- [template] → Reproducible Runtime Setup
	- [template] → Modular, Composable Architecture
	- [template] → Automation-First Workflows
	- [template] → Standard Protocols & Open-Source Libraries
	- [template] → Explicit Versioning & Configuration Management
	- [template] → Local Testability
	- [template] → Deployment Automation
	- [template] → Documentation & Pattern Consistency
- Added sections:
	- Repo Structure
	- Delivery Workflow & Reviews
- Removed sections:
	- Generic placeholder sections [SECTION_2_NAME], [SECTION_3_NAME]
- Templates requiring updates:
	- ✅ .specify/templates/plan-template.md (structurally aligned)
	- ✅ .specify/templates/spec-template.md (structurally aligned)
	- ✅ .specify/templates/tasks-template.md (structurally aligned)
-->

# Story-Telling Constitution

## Core Principles

### I. Reproducible Runtime Setup

- The project MUST provide a `.devcontainer/` configuration so that any
	contributor can launch a fully working environment in one click (Codespaces
	or local Dev Container).
- The devcontainer MUST install all required tooling (Python, `uv`, `azd`,
	Azure CLI, Spec Kit CLI) without manual steps.
- Environment variables MUST be documented in a `.env.example` file listing
	every required and optional key with placeholder values.
- Secrets MUST NEVER be committed; `.env` MUST be in `.gitignore`.
- The `postCreateCommand` or equivalent hook MUST leave the repo ready to
	run (`pip install -r requirements.txt` or `uv sync`) so `python main.py`
	or equivalent works immediately.

Rationale: A reproducible runtime eliminates "works on my machine" failures
and lets new contributors start contributing within minutes.

### II. Modular, Composable Architecture

- Agent capabilities, tools, workflows, and shared logic MUST be structured
	as small, composable modules (separate files, classes, or packages) rather
	than monolithic scripts.
- Each module MUST have a single, clear responsibility and a stable interface
	(function signature, class API, or CLI entrypoint).
- Shared behaviors (logging, client setup, configuration loading, deploy
	helpers) MUST live in reusable utilities rather than being copy-pasted.
- New scenarios SHOULD be assembled primarily by recombining existing modules
	before introducing new abstractions.
- Auto-discovery patterns (e.g., `__init__.py` with `AGENT_CONFIG` dicts)
	SHOULD be used so that adding a new component requires only creating a
	folder — no manual registration.

Rationale: Modular components make it easy to mix, match, and compare
patterns without rewriting large amounts of code.

### III. Automation-First Workflows

- Repetitive tasks (environment setup, formatting, linting, testing,
	deployment) MUST be automated via scripts, `make` targets, or `azd` hooks
	rather than manual step lists only.
- Runnable examples MUST be executable with a single documented command
	(e.g., `azd up`, `python src/main.py`, `make run`).
- CI hooks, pre-commit hooks, or GitHub Actions MAY be introduced but MUST
	remain simple and transparent.
- Any non-obvious manual steps (external services, credentials, feature
	flags) MUST be captured in documentation next to the code that requires
	them.

Rationale: Automation reduces friction, supports repeatable workflows, and
makes complex scenarios approachable for new contributors.

### IV. Standard Protocols & Open-Source Libraries

- The project MUST prefer standard, open protocols for agent communication:
	MCP (Model Context Protocol) for tool exposure, A2A (Agent-to-Agent) for
	inter-agent calls, and AG-UI for user-facing interfaces.
- Dependencies SHOULD come from established open-source libraries (e.g.,
	Microsoft Agent Framework, LangGraph, azure-ai-projects SDK) rather than
	custom reimplementations.
- When a standard protocol or library covers a use case, it MUST be adopted
	over a bespoke solution unless a documented technical limitation prevents it.
- Protocol versions and SDK compatibility MUST be explicitly noted in
	`requirements.txt` or `pyproject.toml` with pinned or minimum versions.

Rationale: Standard protocols ensure interoperability, reduce vendor lock-in,
and leverage community-maintained quality.

### V. Explicit Versioning & Configuration Management

- The project MUST use semantic versioning (MAJOR.MINOR.PATCH) for releases
	and the constitution itself.
- All configuration MUST be loaded from environment variables via a central
	config module (e.g., `config/settings.py` or `src/config.py`) using
	`python-dotenv` or equivalent.
- Configuration MUST support layered overrides: `.env` defaults → environment
	variables → CLI flags.
- `azure.yaml` MUST declare the `azd` metadata template version so
	infrastructure and app versions are synchronized.
- Breaking changes in configuration keys MUST be documented in release notes
	and the `.env.example` file updated.

Rationale: Explicit versioning and centralized configuration prevent drift
and make deployments predictable.

### VI. Local Testability

- Every agent, tool, and workflow MUST be runnable locally without deploying
	to Azure (using local models, mock services, or GitHub Models as a free
	tier).
- A DevUI or local test harness MUST be available so developers can inspect
	agent activities, metrics, and traces during development.
- Integration tests that require cloud resources MUST be clearly marked and
	skippable via an environment flag (e.g., `SKIP_CLOUD_TESTS=1`).
- The feedback loop from code change to observable result MUST be under 30
	seconds for unit-level tests.

Rationale: Fast local feedback loops accelerate development and reduce
dependency on cloud availability.

### VII. Deployment Automation

- Deployment MUST be achievable with a single command (`azd up`) that
	provisions infrastructure and deploys application code end-to-end.
- Infrastructure MUST be defined as code (Bicep, Terraform, or ARM) in an
	`infra/` directory, versioned alongside application code.
- Post-deploy hooks in `azure.yaml` MUST handle image builds, agent
	registration, and workflow deployment automatically.
- Adding a new agent MUST require only creating a new folder with code and
	config — no manual changes to deploy scripts or `azure.yaml`.
- Cleanup MUST be a single command (`azd down`) that removes all provisioned
	resources.

Rationale: One-command deployment and teardown eliminate manual errors and
make the project safe to experiment with.

### VIII. Documentation & Pattern Consistency

- Every non-trivial component (agent, workflow, tool) MUST have accompanying
	documentation: at minimum, a short description and run steps in a local
	`README.md` or the root `README.md`.
- When introducing a new pattern, the documentation MUST explicitly name it
	and explain its intent and trade-offs.
- Similar problems MUST be solved using consistent patterns and structure
	(folder layout, naming conventions, entrypoints) unless there is a
	deliberate, documented reason to diverge.
- Any intentional deviation from existing patterns MUST be called out in
	comments or docs with a short explanation of why.

Rationale: Clear documentation and consistent patterns lower cognitive load
and help contributors transfer learning across the codebase.

## Repo Structure

The repository MUST follow this canonical layout:

```
.devcontainer/              # Dev container config (Dockerfile + devcontainer.json)
.github/                    # GitHub Actions, copilot-instructions, issue templates
.specify/                   # Spec Kit configuration, memory, templates
.vscode/                    # VS Code settings, launch configs, extensions
infra/                      # Infrastructure-as-Code (Bicep/Terraform)
  core/                     # Reusable IaC modules
  main.bicep                # Entry point
  main.parameters.json      # Parameter defaults
src/
  agents/                   # One folder per agent (code + Dockerfile + config)
    <agent-name>/
      __init__.py           # AGENT_CONFIG dict for auto-discovery
      agent.py              # Agent implementation
      Dockerfile            # Container definition
  config/                   # Centralized configuration loader
  workflows/                # Workflow YAML definitions
  deploy_agents.py          # Orchestrator script
  deploy_helpers.py         # Shared deployment utilities
.env.example                # Documented environment variable template
azure.yaml                  # azd project definition + hooks
requirements.txt            # Python dependencies with pinned versions
README.md                   # Project overview, quickstart, architecture
```

New agents are added by creating a folder under `src/agents/` with the standard
files — no other registration needed.

## Delivery Workflow & Reviews

- New contributions MUST state which principles they exemplify (e.g., in PR
	descriptions or commit messages).
- Before merging, reviewers MUST verify that new or changed code:
	- Keeps examples runnable with documented commands.
	- Preserves or improves readability and modularity.
	- Adds or updates documentation when behavior or patterns change.
	- Maintains local testability (no hard cloud dependencies without skip flags).
- Experiments that graduate to "canonical" examples MUST be stabilized:
	interfaces clarified, docs updated, and any experimental flags or hacks
	removed.
- All deployment changes MUST be tested via `azd up` in a scratch
	environment before merging.

Rationale: A lightweight but explicit workflow ensures the repository remains
approachable while evolving quickly.

## Governance

- This constitution defines non-negotiable expectations for all code,
	infrastructure, and documentation in this repository.
- Amendments MUST:
	- Be documented as a version bump in the constitution footer.
	- Include a short Sync Impact Report comment at the top of this file.
	- Be reviewed by at least one maintainer familiar with the project goals.
- Versioning follows semantic rules:
	- MAJOR: Remove or fundamentally redefine a principle or governance rule.
	- MINOR: Add a new principle, section, or materially expand guidance.
	- PATCH: Clarify wording, fix typos, or adjust examples without changing
		meaning.
- All PRs touching core agents, workflows, or infrastructure SHOULD include
	a brief "Constitution Check" note confirming alignment or explaining
	intentional deviations.

Rationale: Explicit governance keeps the project coherent as more patterns
and contributors are added over time.

**Version**: 1.0.0 | **Ratified**: 2026-05-28 | **Last Amended**: 2026-05-28
