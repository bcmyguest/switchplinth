"""`switchplinth setup`: resolve a plan, then run its six steps in order.

Collaborators arrive through `WizardContext`, so tests swap the console,
environment, platform, runtime, and verifier without patching.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from switchplinth.setup.clients import CLIENT_LABEL, FILE_CLIENTS, SERVER_NAME, register_claude_code, register_file_client, snippet
from switchplinth.setup.connection import connection_record
from switchplinth.setup.plan import WINDOWS, SetupPlan, add_arguments, resolve_plan
from switchplinth.setup.prompts import ConsolePrompter, Prompter, SetupError, UnattendedPrompter
from switchplinth.setup.runtime import DockerRuntime, LocalRuntime, Runtime
from switchplinth.setup.verify import VerifyResult, verify_http, verify_stdio
from switchplinth.setup.workspace import config_home, ensure_sample, source_checkout

STATUS_LABEL = {"supported": "pass", "unsupported": "n/a ", "error": "FAIL"}
EXPECTED_TOOLS = {"list_decisions", "search_decisions", "inspect_architecture", "inspect_entity"}


@dataclass
class WizardContext:
    env: Mapping[str, str]
    out: Callable[[str], None] = print
    prompter: Prompter | None = None
    platform: str = sys.platform
    which: Callable[[str], str | None] = shutil.which
    runtime_factory: Callable[[SetupPlan, "WizardContext", Prompter], Runtime] | None = None
    verify_stdio: Callable[..., VerifyResult] = verify_stdio
    verify_http: Callable[[str], VerifyResult] = verify_http
    list_models: Callable[..., list[str]] | None = None


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(prog="switchplinth setup", description="Set up a repository, run mode, model connection, and MCP client.")
    add_arguments(parser)
    return parser


def default_runtime(plan: SetupPlan, context: WizardContext, prompter: Prompter) -> Runtime:
    if plan.mode == "local":
        return LocalRuntime(plan.repo, context.env)
    checkout = source_checkout()
    if checkout is None:
        raise SetupError("Docker mode needs the source checkout with docker-compose.yml; this install has none. Use --mode local.")
    credential = plan.connection.credential_env if plan.connection.enabled else None
    # --yes accepts every other confirmation, so remounting a running project needs its own flag.
    confirm_replace = None
    if plan.replace_workspace:
        confirm_replace = lambda _question: True  # noqa: E731
    elif prompter.interactive:
        confirm_replace = lambda question: prompter.confirm(question, default=False)  # noqa: E731
    return DockerRuntime(plan.repo, checkout, config_home(context.env) / "switchplinth", plan.project, dict(plan.ports), credential, context.env, context.out, confirm_replace=confirm_replace)


def print_diagnostics(report: dict[str, Any], out: Callable[[str], None]) -> bool:
    """Print one line per capability; return whether the model answered chat requests."""
    for name, result in report["capabilities"].items():
        reason = f" ({result.get('normalized_error') or result.get('raw_error')})" if result["status"] != "supported" else ""
        out(f"    {STATUS_LABEL.get(result['status'], result['status'])}  {name}{reason}")
    return report["capabilities"]["structured_output"]["status"] == "supported"


def register(plan: SetupPlan, context: WizardContext, prompter: Prompter) -> str:
    command = list(plan.server_command)
    out = context.out
    if plan.client == "print":
        for client in ("claude-code", *FILE_CLIENTS):
            out(f"  {CLIENT_LABEL[client]}:")
            out("\n".join(f"    {line}" for line in snippet(client, command, plan.claude_scope).splitlines()))
        return "printed"
    if context.platform == WINDOWS:
        out(f"  On Windows setup writes no client config and runs no client CLI. Add this to {CLIENT_LABEL[plan.client]} yourself:")
        out("\n".join(f"    {line}" for line in snippet(plan.client, command, plan.claude_scope).splitlines()))
        return "printed"
    if plan.client == "claude-code":
        return register_claude_code(command, plan.claude_scope, prompter, out, context.which)
    return register_file_client(plan.client, command, context.platform, context.env, prompter, out)


def execute(plan: SetupPlan, context: WizardContext, prompter: Prompter) -> int:
    out = context.out
    failures: list[str] = []

    out("\n[1/6] Repository")
    if plan.sample:
        repo, created = ensure_sample(plan.repo)
        out(f"  {'Bootstrapped' if created else 'Reusing'} the food-delivery sample at {repo}")

    out(f"\n[2/6] Run mode: {plan.mode}")
    runtime = (context.runtime_factory or default_runtime)(plan, context, prompter)
    if plan.mode == "docker":
        out("  Building and starting the stack (the first build takes a few minutes)...")
    runtime.start()

    out("\n[3/6] Model connection")
    if plan.connection.enabled:
        record = connection_record(plan.connection, docker=plan.mode == "docker")
        runtime.save_connection(record)
        credential = f"credential reference {record['credential_ref']}" if "credential_ref" in record else "no credential"
        out(f"  Saved connection '{record['id']}' under {plan.repo / '.decision' / 'connections'} ({credential})")
        out("  Diagnostics:")
        if not print_diagnostics(runtime.diagnose(record["id"]), out):
            failures.append("model diagnostics")
    else:
        out("  None: deterministic extraction and the local vector fallback; no model needed.")

    out("\n[4/6] First scan")
    if plan.scan:
        summary = runtime.scan()
        out(f"  {summary.documents} documents, {summary.passages} passages, {summary.decisions} decisions, {summary.entities} entities (vector index: {summary.vector_index})")
    else:
        out("  Skipped (--no-scan).")

    out(f"\n[5/6] Register MCP server with {plan.client}")
    register(plan, context, prompter)

    out("\n[6/6] Verify")
    if plan.verify:
        try:
            result = context.verify_stdio(list(plan.server_command), context.env)
            missing = EXPECTED_TOOLS - set(result.tools)
            out(f"  stdio: initialize ok ({result.server_name}); tools/list: {', '.join(result.tools)}")
            if missing:
                failures.append(f"stdio MCP missing tools {sorted(missing)}")
        except Exception as exc:  # report every verification failure, then exit non-zero
            failures.append("stdio MCP verify")
            out(f"  stdio: FAILED: {type(exc).__name__}: {exc}")
        if plan.mode == "docker":
            url = f"http://127.0.0.1:{plan.ports['backend']}/mcp"
            try:
                result = context.verify_http(url)
                out(f"  http {url}: initialize ok; tools/list: {', '.join(result.tools)}")
            except Exception as exc:
                failures.append("HTTP MCP verify")
                out(f"  http {url}: FAILED: {type(exc).__name__}: {exc}")
    else:
        out("  Skipped (--no-verify).")

    out("\nNext:")
    out(f"  Run the MCP server by hand: {shlex.join(plan.server_command)}")
    if plan.mode == "docker":
        out("  MCP clients use the local stdio server above; the container's HTTP /mcp is for clients that speak HTTP.")
    if plan.client == "claude-code" and context.platform != WINDOWS and context.which("claude"):
        out(f"  Check Claude Code:          claude mcp get {SERVER_NAME}")
    for line in runtime.next_steps():
        out(f"  {line}")
    out(f"  Rerun setup any time; it is idempotent: switchplinth setup {'--sample' if plan.sample else '--repo ' + shlex.quote(str(plan.repo))}")
    if failures:
        out(f"\nSetup finished with problems: {', '.join(failures)}.")
        return 1
    out("\nSetup complete.")
    return 0


def run_setup(argv: list[str], context: WizardContext) -> int:
    args = build_parser().parse_args(argv)
    return run_parsed(args, context)


def run_parsed(args: argparse.Namespace, context: WizardContext) -> int:
    prompter = context.prompter or (UnattendedPrompter() if args.yes else ConsolePrompter())
    out = context.out
    try:
        out("Switchplinth setup" + (" (unattended)" if not prompter.interactive else ": press Enter to accept the value in parentheses."))
        kwargs = {"list_models": context.list_models} if context.list_models else {}
        plan = resolve_plan(args, prompter, context.env, out, context.which, platform=context.platform, **kwargs)
        out("\nPlan:")
        for line in plan.describe():
            out(f"  {line}")
        if not prompter.confirm("Proceed?", default=True):
            out("Nothing changed.")
            return 1
        return execute(plan, context, prompter)
    except SetupError as exc:
        out(f"\nSetup stopped: {exc}")
        return 2
    except KeyboardInterrupt:
        out("\nSetup interrupted.")
        return 130


def main(args: argparse.Namespace) -> None:
    raise SystemExit(run_parsed(args, WizardContext(env=dict(os.environ), out=lambda line: print(line, flush=True))))
