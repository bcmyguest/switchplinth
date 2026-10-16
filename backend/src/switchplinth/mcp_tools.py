"""MCP tool definitions shared by the HTTP mount and the stdio entry point."""

from __future__ import annotations

from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from switchplinth import MCP_SERVER_NAME, __version__
from switchplinth.service import DecisionService

SERVER_INSTRUCTIONS = (
    "Read-only access to architecture decisions extracted from this repository's Markdown and "
    "`.decision/` YAML. Call list_decisions first to learn decision and option IDs. A `selections` "
    "map ({decision_id: option_id}) previews a what-if scenario; omit it for the repository's "
    "selected options. Previews never write files. diff_scenarios compares two selection maps. Graph, "
    "search, and diff results carry a `receipt`; call the same tool again later and compare "
    "`receipt.digest` to tell whether the canonical inputs changed."
)
SELECTIONS_HELP = (
    "`selections` (optional) maps decision ID to option ID, using IDs from list_decisions, to "
    "preview a what-if scenario; decisions not listed keep their repository-selected option. "
    "Nothing is written."
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def register_tools(server: FastMCP, get_service: Callable[[], DecisionService]) -> None:
    """Register the read-only decision tools; `get_service` returns the current repository service."""

    @server.tool(annotations=READ_ONLY, description=(
        "List every decision with its id, title, status, selected_option, and options (id, title). "
        "Use this first to find the decision and option IDs that `selections` and other tools need. "
        "`needs_review` is true when extraction rejected the option deltas and a human must fix them. "
        + SELECTIONS_HELP
    ))
    def list_decisions(selections: dict[str, str] | None = None) -> dict[str, Any]:
        rendered = get_service().graph_json(selections)
        decisions = [
            {
                "id": decision["id"],
                "title": decision["title"],
                "status": decision["status"],
                "selected_option": decision["selected_option"],
                "options": [{"id": option["id"], "title": option["title"]} for option in decision["options"]],
                "needs_review": "extraction_review" in decision,
            }
            for decision in rendered["decisions"]
        ]
        return {"decisions": decisions, "selections": rendered["scenario"]["selections"], "receipt": rendered["receipt"]}

    @server.tool(annotations=READ_ONLY, description=(
        "Search the repository's Markdown passages and decision claims. Use for questions such as "
        "'Why are we using Kafka?' or to find where a component is discussed. Returns an extractive "
        "`answer`, matching `evidence` passages with source paths, related `claims` and "
        "`entities`, and `grounded`. `grounded` is true "
        "only when cited passages support the answer; for queries starting with 'why', effective "
        "claims must cite the returned passages. Retrieval is lexical plus a vector index (a "
        "deterministic local fallback unless an embedding model is configured), not an LLM answer. "
        + SELECTIONS_HELP
    ))
    def search_decisions(query: str, selections: dict[str, str] | None = None) -> dict[str, Any]:
        return get_service().search(query, selections)

    @server.tool(annotations=READ_ONLY, description=(
        "Return the full compiled architecture graph: entities, relationships, decisions with "
        "option deltas, aliases, claims, evidence, identity groups, and a `scenario` block with "
        "added/removed/changed records, conflicts, invalid assumptions, affected decisions, and "
        "`impact` (downstream dependents of what the selections remove or replace versus the "
        "repository-selected options). Large; prefer list_decisions or inspect_entity for targeted questions. "
        + SELECTIONS_HELP
    ))
    def inspect_architecture(selections: dict[str, str] | None = None) -> dict[str, Any]:
        return get_service().graph_json(selections)

    @server.tool(annotations=READ_ONLY, description=(
        "Compare two scenarios given as `before_selections` and `after_selections` maps "
        "({decision_id: option_id}; an omitted or empty map means the repository-selected options). "
        "Returns `selection_changes`; `entities` and `relationships` each split into added, removed, "
        "and changed; `conflicts` and `invalid_assumptions` split into appeared and disappeared; "
        "`affected_decisions` with reasons; and `impact`: for each removed or replaced element, the "
        "entities that depend on it over relationships in the before scenario (transitive, with path "
        "and depth, capped at `impact.max_depth`); each dependent's outgoing edges to now-missing "
        "entities are marked `rewired` (same kind to a new target) or `dangling` (`points_at_missing`). "
        "Impact is relationship-based only, with no code analysis; see `impact.limits`. Nothing is written."
    ))
    def diff_scenarios(before_selections: dict[str, str] | None = None, after_selections: dict[str, str] | None = None) -> dict[str, Any]:
        return get_service().diff_scenarios(before_selections, after_selections)

    @server.tool(annotations=READ_ONLY, description=(
        "Return one entity (component, service, technology, datastore, ...) by `entity_id`, taken "
        "from inspect_architecture or search results: its relationships, aliases, claims, cited "
        "evidence, related decisions (selected option with rationale, all options), and identity "
        "groups, suggestions, and conflicts. Errors on an unknown ID. "
        + SELECTIONS_HELP
    ))
    def inspect_entity(entity_id: str, selections: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            return get_service().entity_detail(entity_id, selections)
        except KeyError as exc:
            raise ToolError(f"Unknown entity {entity_id}") from exc


def create_mcp_server(get_service: Callable[[], DecisionService]) -> FastMCP:
    """Build a FastMCP server exposing the decision tools for any transport."""
    server = FastMCP(MCP_SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    # FastMCP takes no version argument; without this, serverInfo.version reports the MCP SDK version.
    server._mcp_server.version = __version__
    register_tools(server, get_service)
    return server
