"""Pre-flight gates for OpenClaw plugin state.

Used by the publishable OV plugin reproduction path. Two gates:

  - assert_openviking_plugin_loaded(profile): refuses if the OV plugin shows
    "requires compiled runtime output" warnings (dist not built) or otherwise
    fails to inspect under the named profile.
  - assert_answer_model_reachable(profile, model): refuses if the named answer
    model is not advertised by any enabled provider plugin on the profile.

Both gates parse OpenClaw CLI output. They are intentionally read-only and
cheap: no /v1/responses calls, no provider API calls.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class PluginGateResult:
    ok: bool
    failures: list[str]
    detail: dict


def _openclaw_bin() -> str:
    path = shutil.which("openclaw")
    if not path:
        raise RuntimeError("openclaw binary not found on PATH")
    return path


def _run(profile: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_openclaw_bin(), "--profile", profile, *args],
        capture_output=True,
        text=True,
        check=False,
    )


# `openclaw plugins doctor` returns "No plugin issues detected" even when
# `plugins.entries.X` warns "requires compiled runtime output". So we parse
# `openclaw plugins list 2>&1` for the warning string directly. Codex flagged
# this and the 2026-05-20 smoke probe confirmed it.
_DIST_MISSING_NEEDLE = "requires compiled runtime output for TypeScript entry"


def collect_plugin_warnings(profile: str) -> list[str]:
    """Return the loader's `Config warnings` block, one entry per warning."""
    result = _run(profile, "plugins", "list")
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    warnings: list[str] = []
    in_block = False
    for line in combined.splitlines():
        stripped = line.strip("│ \t")
        if not in_block:
            if "Config warnings" in line:
                in_block = True
            continue
        if line.strip().startswith("├") or line.strip().startswith("╰"):
            in_block = False
            continue
        if stripped.startswith("- "):
            warnings.append(stripped[2:].strip())
    return warnings


def assert_openviking_plugin_loaded(profile: str) -> PluginGateResult:
    """Return PluginGateResult(ok=True) when the OV plugin is loadable."""
    failures: list[str] = []
    detail: dict = {"profile": profile}

    warnings = collect_plugin_warnings(profile)
    detail["plugin_warnings"] = warnings
    dist_missing = [w for w in warnings if "openviking" in w and _DIST_MISSING_NEEDLE in w]
    if dist_missing:
        failures.append(
            "OpenViking plugin dist not built. Rebuild from "
            "~/.openclaw/extensions/openviking with tsc emitting to dist/, "
            "or reinstall the plugin: see docs/design/openviking-memory-eval-plan.md "
            "Phase 4 step 7.1."
        )

    inspect = _run(profile, "plugins", "inspect", "openviking")
    inspect_combined = (inspect.stdout or "") + "\n" + (inspect.stderr or "")
    detail["inspect_returncode"] = inspect.returncode
    if "Plugin not found" in inspect_combined:
        failures.append(
            f"`openclaw --profile {profile} plugins inspect openviking` returns "
            "'Plugin not found'. Install the plugin into the profile: "
            f"`openclaw --profile {profile} plugins install ~/.openclaw/extensions/openviking` "
            "then restart the gateway."
        )
        detail["inspect_status"] = "not_found"
    else:
        detail["inspect_status"] = "ok"
        for line in inspect_combined.splitlines():
            if line.lstrip().startswith("Source:"):
                detail["plugin_source"] = line.split("Source:", 1)[1].strip()
            elif line.lstrip().startswith("Version:"):
                detail["plugin_version"] = line.split("Version:", 1)[1].strip()
            elif line.lstrip().startswith("Status:"):
                detail["plugin_status"] = line.split("Status:", 1)[1].strip()

    return PluginGateResult(ok=not failures, failures=failures, detail=detail)


def assert_answer_model_reachable(profile: str, model: str) -> PluginGateResult:
    """Return PluginGateResult(ok=True) when the model id appears reachable.

    The check is best-effort: we look up the provider implied by the model id
    prefix (e.g. ``deepseek/deepseek-v4-flash`` → provider ``deepseek``) and
    assert the provider plugin is loaded under the named profile. We do NOT
    issue a paid `/v1/responses` call here — that's the caller's job at smoke
    time.
    """
    failures: list[str] = []
    detail: dict = {"profile": profile, "model": model}

    if "/" not in model:
        provider = None
    else:
        provider = model.split("/", 1)[0]
    detail["implied_provider"] = provider

    if provider:
        inspect = _run(profile, "plugins", "inspect", provider)
        combined = (inspect.stdout or "") + "\n" + (inspect.stderr or "")
        detail["provider_inspect_returncode"] = inspect.returncode
        if "Plugin not found" in combined:
            failures.append(
                f"Provider plugin '{provider}' required by model '{model}' is not "
                f"installed under profile '{profile}'. Enable it with "
                f"`openclaw --profile {profile} plugins enable {provider}` "
                "(may need to widen plugins.allow first) then restart the gateway."
            )
        else:
            for line in combined.splitlines():
                if line.lstrip().startswith("Status:"):
                    status = line.split("Status:", 1)[1].strip()
                    detail["provider_status"] = status
                    if status not in {"loaded", "enabled"}:
                        failures.append(
                            f"Provider plugin '{provider}' has status '{status}' "
                            "(expected 'loaded' or 'enabled')."
                        )
    else:
        failures.append(
            f"Model id '{model}' has no provider prefix; cannot determine which "
            "provider plugin must be enabled. Use a fully-qualified id like "
            "'deepseek/deepseek-v4-flash' or 'byteplus/seed-2.0-code'."
        )

    return PluginGateResult(ok=not failures, failures=failures, detail=detail)


def openclaw_plugin_install_record(plugin_id: str, profile: str | None = None) -> dict | None:
    """Read the `.ov-install-state.json` next to the plugin's install root.

    Returns None when the plugin is not installed or the record is missing.
    """
    inspect = _run(profile or "default", "plugins", "inspect", plugin_id)
    combined = (inspect.stdout or "") + "\n" + (inspect.stderr or "")
    install_path: str | None = None
    for line in combined.splitlines():
        if line.lstrip().startswith("Install path:"):
            install_path = line.split("Install path:", 1)[1].strip()
            break
    if not install_path:
        return None
    # Expand ~ to home explicitly to keep this side-effect free.
    if install_path.startswith("~"):
        import os
        install_path = os.path.expanduser(install_path)
    from pathlib import Path
    state_file = Path(install_path) / ".ov-install-state.json"
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
