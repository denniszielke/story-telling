import json
import logging
import os
import re
import time
import uuid
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from .content_internet_extractor import load_prompt

load_dotenv()

logger = logging.getLogger(__name__)

SCENARIO_SECTION_TITLES = {
    "scenario",
    "scenario description and customer context",
    "scenario description and problem space",
}

# Public, checked-in analysis prompt. Fetched at runtime so the sandbox always
# analyses with the same instructions that live in the repository, keeping a
# single source of truth that is easy to maintain.
DEFAULT_PROMPT_URL = (
    "https://raw.githubusercontent.com/denniszielke/story-telling/main/"
    "src/prompts/repository-extraction.md"
)

# Host families the sandbox must reach for the Copilot CLI + git clone to work.
_ALLOW_HOSTS = (
    "*.github.com",
    "*.githubusercontent.com",
    "gh.io",
    "*.github.io",
    "*.githubassets.com",
    "*.npmjs.com",
    "bootstrap.pypa.io",
    "pypi.org",
    "*.pypi.org",
    "files.pythonhosted.org",
    "archive.ubuntu.com",
    "security.ubuntu.com",
    "*.ubuntu.com",
    "astral.sh",
    "*.astral.sh",
)

# Hosts that need an injected Authorization header so the Copilot CLI can
# authenticate without an interactive login. Mirrors the yolo-coding demo.
_INJECT_HOSTS = (
    ("api.github.com", "token", "github-api-auth"),
    ("api.enterprise.githubcopilot.com", "Bearer", "copilot-enterprise-auth"),
    ("telemetry.enterprise.githubcopilot.com", "Bearer", "copilot-telemetry-auth"),
)


class RemoteRepositoryContentExtractor:
    """Repository extractor that runs the analysis inside an ACA sandbox.

    Implements the same external interface as ``RepositoryContentExtractor``
    (``enrich_document`` / ``enrich_documents``) so the two are interchangeable.

    For each repository document it boots an Azure Container Apps sandbox,
    installs the GitHub Copilot CLI, clones the public repository, and asks the
    CLI to analyse the code, dependencies, solution and architecture pattern
    using the checked-in ``repository-extraction.md`` prompt. The CLI writes a
    JSON index entry inside the sandbox which is then downloaded back to the
    host and merged into the document.
    """

    def __init__(
        self,
        openai_endpoint: Optional[str] = None,
        chat_model: Optional[str] = None,
        api_version: Optional[str] = None,
        *,
        github_pat: Optional[str] = None,
        prompt_url: Optional[str] = None,
        resource_group_name: Optional[str] = None,
        sandbox_group_name: Optional[str] = None,
        location: Optional[str] = None,
    ):
        # Kept for interface parity with the local extractor; the LLM work is
        # delegated to the Copilot CLI inside the sandbox.
        self.openai_endpoint = openai_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.chat_model = chat_model or os.getenv("AZURE_OPENAI_LARGE_CHAT_DEPLOYMENT_NAME", "gpt-5.4")
        self.api_version = api_version or os.getenv("OPENAI_API_VERSION", "2024-10-21")

        self.github_pat = github_pat or os.getenv("PAT", "")
        self.prompt_url = prompt_url or os.getenv("REPOSITORY_EXTRACTION_PROMPT_URL", DEFAULT_PROMPT_URL)
        self.resource_group_name = resource_group_name or os.getenv("RESOURCE_GROUP_NAME", "aca-sandboxes-rg")
        self.sandbox_group_name = sandbox_group_name or os.getenv("SANDBOX_GROUP_NAME", "repo-extraction")
        self.location = location or os.getenv("LOCATION", "westus3")

        # Upper bound on a single Copilot CLI analysis run inside the sandbox.
        # Without it a stuck agent only ends when the data-plane connection
        # drops (observed as a ~17 minute hang then RemoteDisconnected).
        self.agent_timeout_seconds = int(
            os.getenv("REPOSITORY_EXTRACTION_AGENT_TIMEOUT", "600")
        )

        self._sandbox_client = None

    # ------------------------------------------------------------------
    # Public interface (mirrors RepositoryContentExtractor)
    # ------------------------------------------------------------------
    def enrich_document(self, document: dict) -> dict:
        if not self._is_repository_document(document):
            return document

        reference = document.get("reference", "")
        parsed = self._parse_github_repo(reference)
        if not parsed:
            logger.warning("Skipping remote repository enrichment for unsupported URL: %s", reference)
            return document

        owner, repo = parsed
        logger.info("Remote enriching repository document '%s' from %s/%s", document.get("id"), owner, repo)

        try:
            entry = self._analyze_repository_in_sandbox(owner, repo)
            document = self._merge_entry(document, entry)
        except Exception as exc:
            logger.error("Failed remote enrichment for document '%s': %s", document.get("id"), exc)

        return document

    def enrich_documents(self, documents: List[dict]) -> List[dict]:
        return [self.enrich_document(document) for document in documents]

    # ------------------------------------------------------------------
    # Document helpers (shared semantics with the local extractor)
    # ------------------------------------------------------------------
    def _is_repository_document(self, document: dict) -> bool:
        objective = (document.get("objective") or "").strip().lower()
        reference = (document.get("reference") or "").strip().lower()
        if objective == "code":
            return True
        return "github.com/" in reference

    def _parse_github_repo(self, url: str) -> Optional[tuple[str, str]]:
        parsed = urlparse((url or "").strip())
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            return None

        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2:
            return None

        owner, repo = path_parts[0], path_parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        return owner, repo

    def _merge_tags(self, existing_tags: List[str], new_tags: List[str]) -> List[str]:
        merged = {str(tag).strip().lower() for tag in existing_tags if str(tag).strip()}
        for tag in new_tags or []:
            value = str(tag).strip().lower()
            if value:
                merged.add(value)
        merged.add("github")
        return sorted(merged)

    def _merge_entry(self, document: dict, entry: dict) -> dict:
        """Merge the JSON entry produced inside the sandbox into the document."""
        scenario = (entry.get("scenario") or "").strip()
        content = (entry.get("content") or "").strip()

        if scenario:
            document["scenario"] = scenario
        elif not document.get("scenario"):
            document["scenario"] = document.get("description", "")

        if content:
            document["content"] = content

        if entry.get("description") and not document.get("description"):
            document["description"] = entry["description"].strip()

        for field in ("classification", "complexity", "context"):
            value = (entry.get(field) or "").strip() if isinstance(entry.get(field), str) else entry.get(field)
            if value and not document.get(field):
                document[field] = value

        document["tags"] = self._merge_tags(document.get("tags", []) or [], entry.get("tags", []) or [])
        return document

    def _coerce_entry(self, raw: str) -> dict:
        """Parse the JSON the Copilot CLI wrote, tolerating stray markdown fences."""
        text = (raw or "").strip()
        if not text:
            raise ValueError("Sandbox produced an empty index entry")

        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1)
        elif not text.lstrip().startswith("{"):
            brace = text.find("{")
            if brace != -1:
                text = text[brace:]

        return json.loads(text)

    # ------------------------------------------------------------------
    # Sandbox orchestration
    # ------------------------------------------------------------------
    def _load_prompt_text(self) -> str:
        """Fetch the public analysis prompt, falling back to the local copy."""
        try:
            with httpx.Client(follow_redirects=True, timeout=30.0) as client:
                response = client.get(self.prompt_url)
                response.raise_for_status()
                return response.text
        except Exception as exc:
            logger.warning("Could not fetch prompt from %s (%s); using local copy", self.prompt_url, exc)
            return load_prompt("repository-extraction.md")

    def _get_sandbox_client(self):
        """Create the sandbox group (and data-plane role assignment) once."""
        if self._sandbox_client:
            return self._sandbox_client

        from azure.identity import AzureCliCredential
        from azure.mgmt.resource.resources import ResourceManagementClient
        from azure.mgmt.authorization import AuthorizationManagementClient
        from azure.containerapps.sandbox import (
            SandboxGroupManagementClient,
            SandboxGroupClient,
            endpoint_for_region,
        )

        credential = AzureCliCredential()
        subscription_id = self._get_subscription_id()

        resource_mgmt_client = ResourceManagementClient(credential, subscription_id)
        if not resource_mgmt_client.resource_groups.check_existence(self.resource_group_name):
            resource_mgmt_client.resource_groups.create_or_update(
                self.resource_group_name, {"location": self.location}
            )
            logger.info("Created resource group '%s'", self.resource_group_name)

        sandboxgroup_mgmt_client = SandboxGroupManagementClient(
            credential,
            subscription_id=subscription_id,
            resource_group=self.resource_group_name,
        )
        existing = next(
            (g for g in sandboxgroup_mgmt_client.list_groups() if g.name == self.sandbox_group_name),
            None,
        )
        if not existing:
            sandboxgroup_mgmt_client.create_group(self.sandbox_group_name, location=self.location)
            logger.info("Created sandbox group '%s'", self.sandbox_group_name)
        sandboxgroup = sandboxgroup_mgmt_client.get_group(self.sandbox_group_name)

        self._ensure_data_plane_role(credential, subscription_id)

        self._sandbox_client = SandboxGroupClient(
            endpoint_for_region(sandboxgroup.location),
            credential,
            subscription_id=subscription_id,
            resource_group=self.resource_group_name,
            sandbox_group=self.sandbox_group_name,
        )
        return self._sandbox_client

    def _get_subscription_id(self) -> str:
        import subprocess

        proc = subprocess.run(
            "az account show --query id -o tsv",
            capture_output=True, text=True, check=True, shell=True,
        )
        return proc.stdout.strip()

    def _ensure_data_plane_role(self, credential, subscription_id: str) -> None:
        import subprocess
        from azure.mgmt.authorization import AuthorizationManagementClient

        auth_client = AuthorizationManagementClient(credential, subscription_id)
        role_name = "Container Apps SandboxGroup Data Owner"
        scope = f"/subscriptions/{subscription_id}/resourceGroups/{self.resource_group_name}"
        role_def = next(auth_client.role_definitions.list(scope, filter=f"roleName eq '{role_name}'"))

        proc = subprocess.run(
            "az ad signed-in-user show --query id -o tsv",
            capture_output=True, text=True, check=True, shell=True,
        )
        principal_id = proc.stdout.strip()
        try:
            auth_client.role_assignments.create(scope, uuid.uuid4(), {
                "role_definition_id": role_def.id,
                "principal_id": principal_id,
                "principal_type": "User",
            })
            logger.info("Assigned '%s'; waiting for propagation", role_name)
            time.sleep(60)
        except Exception as exc:
            if "RoleAssignmentExists" in str(exc) or "Conflict" in str(exc):
                logger.info("Data-plane role already assigned")
            else:
                raise

    def _analyze_repository_in_sandbox(self, owner: str, repo: str) -> dict:
        if not self.github_pat:
            raise ValueError("PAT is not set; the GitHub Copilot CLI requires a fine-grained PAT")

        client = self._get_sandbox_client()
        prompt_text = self._load_prompt_text()

        run_id = uuid.uuid4().hex[:8]
        labels = {"scenario": "repo-extraction", "run": run_id}

        sandbox = None
        try:
            sandbox = client.begin_create_sandbox(
                disk="ubuntu",
                cpu="2000m",
                memory="4096Mi",
                labels=labels,
            ).result()
            logger.info("Sandbox ready: %s (run=%s)", sandbox.sandbox_id, run_id)
            self._wait_exec_up(sandbox)

            self._install_toolchain(sandbox)
            self._configure_credentials(sandbox)
            self._lock_down_egress(sandbox)

            # Keep the repo, prompt and output file all under a single working
            # directory. The Copilot CLI restricts file tools to its working
            # directory tree, so the prompt/output must live inside it - placing
            # them at /root (a parent of the repo cwd) triggers "Permission
            # denied" and forces the agent into brittle workarounds.
            work_dir = "/root/work"
            self._exec_check(sandbox, f"mkdir -p {work_dir}", label="mkdir-work")

            repo_dir = f"{work_dir}/{repo}"
            clone_url = f"https://github.com/{owner}/{repo}.git"
            self._exec_check(
                sandbox,
                f"git clone --depth 50 {clone_url} {repo_dir}",
                label="git-clone",
            )

            prompt_path = f"{work_dir}/repository-extraction.md"
            output_path = f"{work_dir}/index-entry.json"
            sandbox.write_file(prompt_path, prompt_text)

            agent_prompt = self._build_agent_prompt(repo_dir, prompt_path, output_path)
            agent_cmd = (
                f"cd {work_dir} && GH_TOKEN={self.github_pat} "
                f"timeout {self.agent_timeout_seconds}s "
                f"bash -lc 'copilot --allow-all-tools -p \"{agent_prompt}\"'"
            )
            exit_code = self._exec_stream(
                sandbox,
                agent_cmd,
                label="copilot-agent",
                max_wait=self.agent_timeout_seconds + 120,
            )
            if exit_code == 124:
                logger.warning(
                    "Copilot agent timed out after %ss", self.agent_timeout_seconds
                )
            elif exit_code != 0:
                logger.warning("Copilot agent exited with code %s", exit_code)

            raw = sandbox.read_file(output_path)
            if isinstance(raw, (bytes, bytearray)):
                raw = bytes(raw).decode("utf-8", errors="replace")
            return self._coerce_entry(raw)
        finally:
            if sandbox is not None:
                try:
                    sandbox.delete()
                    logger.info("Sandbox %s deleted", sandbox.sandbox_id)
                except Exception as exc:
                    logger.warning("Sandbox delete warning: %s", exc)

    def _build_agent_prompt(self, repo_dir: str, prompt_path: str, output_path: str) -> str:
        return (
            f"Read the analysis instructions in {prompt_path}. "
            f"Inspect the repository cloned at {repo_dir} - its code, dependencies, "
            f"solution structure and architecture pattern - and follow those "
            f"instructions exactly to produce the analysis. "
            f"Then write a single JSON object to {output_path} with EXACTLY these "
            f"fields: description (one-sentence summary), scenario (the Scenario "
            f"section covering context and problem only), content (the remaining "
            f"analysis sections as markdown), tags (array of lowercase "
            f"technology/topic strings), classification (short label), complexity "
            f"(one of low, medium, high). Write ONLY valid JSON to {output_path} "
            f"with no markdown code fences. Do not modify, commit or push any "
            f"repository files."
        )

    # ------------------------------------------------------------------
    # Sandbox bootstrap helpers
    # ------------------------------------------------------------------
    def _install_toolchain(self, sandbox) -> None:
        self._exec_check(
            sandbox,
            "apt-get update -qq && apt-get install -y -qq git curl jq",
            label="apt",
        )
        self._exec_check(
            sandbox,
            (
                "curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg"
                " -o /usr/share/keyrings/githubcli-archive-keyring.gpg && "
                "chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && "
                'echo "deb [arch=amd64 signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg]'
                ' https://cli.github.com/packages stable main"'
                " > /etc/apt/sources.list.d/github-cli.list && "
                "apt-get update -qq && apt-get install -y -qq gh"
            ),
            label="gh-install",
        )
        r = sandbox.exec(
            f"GH_TOKEN={self.github_pat} timeout 180s bash -lc "
            "'curl -fsSL https://gh.io/copilot-install | bash'"
        )
        if r.exit_code != 0:
            logger.warning("Copilot CLI install warning: %s", (r.stderr or r.stdout or "")[:300])

    def _configure_credentials(self, sandbox) -> None:
        self._exec_check(
            sandbox,
            f"printf 'machine github.com\\n  login x-access-token\\n  password {self.github_pat}\\n'"
            " > ~/.netrc && chmod 600 ~/.netrc",
            label="netrc",
        )
        self._exec_check(
            sandbox,
            f"echo 'export GH_TOKEN={self.github_pat}' >> ~/.bashrc && "
            f"echo 'export GH_TOKEN={self.github_pat}' >> ~/.profile",
            label="gh-token-env",
        )
        self._exec_check(sandbox, 'git config --global user.email "repo-extractor@sandbox.local"', label="git-email")
        self._exec_check(sandbox, 'git config --global user.name "Repo Extractor"', label="git-name")

    def _lock_down_egress(self, sandbox) -> None:
        from azure.containerapps.sandbox import EgressHeader

        sandbox.set_egress_default("Deny")
        for host in _ALLOW_HOSTS:
            sandbox.add_egress_host_rule(host, action="Allow")
        for host, scheme, name in _INJECT_HOSTS:
            sandbox.add_egress_transform_rule(
                host=host,
                headers=[EgressHeader(
                    operation="Set",
                    name="Authorization",
                    value=f"{scheme} {self.github_pat}",
                )],
                name=name,
            )

    def _wait_exec_up(self, sandbox, *, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if sandbox.exec("true").exit_code == 0:
                    return
            except Exception:
                pass
            time.sleep(2)
        raise RuntimeError("sandbox exec endpoint did not come up in time")

    def _exec_check(self, sandbox, cmd: str, *, label: str = "") -> str:
        r = sandbox.exec(cmd)
        if r.exit_code != 0:
            tag = f" [{label}]" if label else ""
            raise RuntimeError(
                f"sandbox exec failed{tag}: exit={r.exit_code}\n"
                f"  cmd : {cmd!r}\n"
                f"  out : {(r.stdout or '')[:400]}\n"
                f"  err : {(r.stderr or '')[:400]}"
            )
        return (r.stdout or "").strip()

    def _exec_stream(self, sandbox, cmd: str, *, poll_interval: float = 3.0, label: str = "", max_wait: Optional[float] = None) -> int:
        """Run cmd in the background and stream its output by polling a log file.

        ``max_wait`` bounds the total time spent polling so a hung run cannot
        block indefinitely; on expiry the background command is killed and
        exit code 124 (timeout convention) is returned.
        """
        tag = uuid.uuid4().hex[:8]
        script_path = f"/tmp/stream_{tag}.sh"
        log_path = f"/tmp/stream_{tag}.log"
        done_path = f"/tmp/stream_{tag}.done"

        sandbox.write_file(script_path, f"#!/bin/bash\n{cmd}\n")
        sandbox.exec(f"chmod +x {script_path}")
        sandbox.exec(
            f"bash -c 'bash {script_path} >{log_path} 2>&1; echo $? >{done_path}' &"
        )

        deadline = time.monotonic() + max_wait if max_wait else None
        lines_shown = 0
        while True:
            time.sleep(poll_interval)

            r = sandbox.exec(f"awk 'NR>{lines_shown}' {log_path} 2>/dev/null || true")
            if r.stdout:
                print(r.stdout, end="", flush=True)
                lines_shown += r.stdout.count("\n")

            done_r = sandbox.exec(f"cat {done_path} 2>/dev/null || true")
            exit_str = (done_r.stdout or "").strip()
            if exit_str and exit_str.lstrip("-").isdigit():
                r = sandbox.exec(f"awk 'NR>{lines_shown}' {log_path} 2>/dev/null || true")
                if r.stdout:
                    print(r.stdout, end="", flush=True)
                return int(exit_str)

            if deadline and time.monotonic() > deadline:
                tag_str = f" [{label}]" if label else ""
                logger.warning("Streamed command%s exceeded max_wait; terminating", tag_str)
                sandbox.exec(f"pkill -f {script_path} 2>/dev/null || true")
                return 124
