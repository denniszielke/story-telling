"""Hosted agent discovery for Foundry deployment.

Scans this package directory for subdirectories that contain a ``Dockerfile``
and exposes them as :class:`HostedAgentConfig` entries. Consumed by
``scripts/deploy_hosted_agents.py`` (to build and deploy) and
``scripts/delete_agents.py`` (to enumerate deployed hosted agents).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_AGENTS_DIR = Path(__file__).resolve().parent

_DEFAULT_CPU = "1"
_DEFAULT_MEMORY = "2Gi"

# Optional per-agent overrides keyed by the agent's directory name.
_AGENT_OVERRIDES: dict[str, dict] = {
    "researcher": {
        "description": (
            "Researcher deep agent — produces architecture proposals grounded "
            "in curated research with human-in-the-loop approval."
        ),
    },
}


@dataclass
class HostedAgentConfig:
    """Configuration for a single hosted agent discovered on disk."""

    name: str
    path: Path
    description: str = ""
    cpu: str = _DEFAULT_CPU
    memory: str = _DEFAULT_MEMORY
    env_vars: dict[str, str] = field(default_factory=dict)


def discover_hosted_agents() -> list[HostedAgentConfig]:
    """Discover hosted agents under this package.

    A subdirectory is treated as a hosted agent when it contains a
    ``Dockerfile``. The directory name becomes the agent name. Hidden
    directories (``.``-prefixed, e.g. ``.venv``) and dunder directories
    (e.g. ``__pycache__``) are ignored.
    """
    configs: list[HostedAgentConfig] = []
    for entry in sorted(_AGENTS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "__")):
            continue
        if not (entry / "Dockerfile").exists():
            continue
        overrides = _AGENT_OVERRIDES.get(entry.name, {})
        configs.append(
            HostedAgentConfig(
                name=entry.name,
                path=entry,
                description=overrides.get("description", f"{entry.name} hosted agent"),
                cpu=overrides.get("cpu", _DEFAULT_CPU),
                memory=overrides.get("memory", _DEFAULT_MEMORY),
                env_vars=overrides.get("env_vars", {}),
            )
        )
    return configs


__all__ = ["HostedAgentConfig", "discover_hosted_agents"]
