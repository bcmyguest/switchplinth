"""Repository validation, the bundled food-delivery sample, and per-user paths."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Mapping

from switchplinth.repository import discover_markdown
from switchplinth.setup.prompts import SetupError

SAMPLE_NAME = "food-delivery"
SAMPLE_BOOTSTRAP = Path("fixtures") / SAMPLE_NAME / "bootstrap.py"
COMPOSE_FILE = "docker-compose.yml"


def source_checkout(start: Path | None = None) -> Path | None:
    """Return the source checkout holding docker-compose.yml and fixtures/, if this install has one."""
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        if (parent / COMPOSE_FILE).is_file() and (parent / SAMPLE_BOOTSTRAP).is_file():
            return parent
    return None


def cache_home(env: Mapping[str, str]) -> Path:
    return Path(env.get("XDG_CACHE_HOME") or Path(env.get("HOME", str(Path.home()))) / ".cache")


def config_home(env: Mapping[str, str]) -> Path:
    return Path(env.get("XDG_CONFIG_HOME") or Path(env.get("HOME", str(Path.home()))) / ".config")


def sample_path(env: Mapping[str, str]) -> Path:
    """Match scripts/demo.sh: one sample under the user's cache directory."""
    workspace = env.get("DECISION_DEMO_WORKSPACE") or str(cache_home(env) / "switchplinth-demo")
    return Path(workspace) / SAMPLE_NAME


def validate_repository(path: Path) -> tuple[Path, int]:
    """Return the resolved repository and its Markdown document count, or raise SetupError."""
    root = path.expanduser().resolve()
    if not root.exists():
        raise SetupError(f"Repository not found: {root}")
    if not root.is_dir():
        raise SetupError(f"Repository is not a directory: {root}")
    if root == Path(root.anchor):
        raise SetupError("Refusing to use the filesystem root as a repository.")
    count = len(discover_markdown(root))
    if count == 0:
        raise SetupError(f"No Markdown files found under {root} (generated and hidden folders such as .git, node_modules, and .decision are skipped).")
    return root, count


def ensure_sample(target: Path, checkout: Path | None = None) -> tuple[Path, bool]:
    """Bootstrap the sample once; return (path, created). An existing bootstrapped sample is reused."""
    if (target / ".decision").is_dir():
        return target.resolve(), False
    if target.exists() and any(target.iterdir()):
        raise SetupError(f"{target} exists, is not empty, and has no .decision/ folder; set DECISION_DEMO_WORKSPACE to another directory or remove it.")
    checkout = checkout or source_checkout()
    if checkout is None:
        raise SetupError("The bundled sample needs a source checkout (fixtures/food-delivery/); this install has none. Pass --repo instead.")
    spec = importlib.util.spec_from_file_location("switchplinth_sample_bootstrap", checkout / SAMPLE_BOOTSTRAP)
    if spec is None or spec.loader is None:
        raise SetupError(f"Cannot load {checkout / SAMPLE_BOOTSTRAP}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target.parent.mkdir(parents=True, exist_ok=True)
    module.bootstrap(target)
    return target.resolve(), True
