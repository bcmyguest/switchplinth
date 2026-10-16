"""Switchplinth backend: architecture decisions from Markdown and portable `.decision/` YAML.

Product identifiers live here, so a rename touches one place in the backend.
The distribution and console-script names live in pyproject.toml.
"""

from importlib.metadata import version as _distribution_version

# pyproject.toml is the single source of the version; this reads the installed metadata.
__version__ = _distribution_version("switchplinth")

PRODUCT_NAME = "Switchplinth"
MCP_SERVER_NAME = "io.github.bcmyguest/switchplinth"
DEFAULT_CACHE_ROOT = "/tmp/switchplinth-cache"
