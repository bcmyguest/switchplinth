"""Prompter seam: the wizard asks every question through one of these adapters.

`ConsolePrompter` reads answers from a text stream. `UnattendedPrompter`
answers with the flag or default value, accepts every confirmation (the user
passed `--yes`), and fails when a required answer has no default.
"""

from __future__ import annotations

import sys
from typing import Callable, Protocol, TextIO


class SetupError(RuntimeError):
    """A setup step failed with a message meant for the user."""


class Prompter(Protocol):
    interactive: bool

    def ask(self, question: str, default: str | None = None, choices: tuple[str, ...] = ()) -> str:
        """Return an answer; `choices` restricts it, `default` answers an empty line."""

    def confirm(self, question: str, default: bool = True) -> bool:
        """Return whether the user accepts the described change."""


class ConsolePrompter:
    interactive = True

    def __init__(self, read_line: Callable[[], str] | None = None, out: TextIO | None = None):
        self._read_line = read_line or sys.stdin.readline
        self._out = out or sys.stdout

    def _line(self, prompt: str) -> str:
        self._out.write(prompt)
        self._out.flush()
        line = self._read_line()
        if line == "":
            raise SetupError("Input ended before setup finished; rerun with --yes and flags for unattended setup.")
        return line.strip()

    def ask(self, question: str, default: str | None = None, choices: tuple[str, ...] = ()) -> str:
        options = f" [{'/'.join(choices)}]" if choices else ""
        suffix = f" ({default})" if default not in (None, "") else ""
        while True:
            answer = self._line(f"{question}{options}{suffix}: ") or (default or "")
            if not answer:
                self._out.write("  An answer is required.\n")
            elif choices and answer not in choices:
                self._out.write(f"  Choose one of: {', '.join(choices)}.\n")
            else:
                return answer

    def confirm(self, question: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        while True:
            answer = self._line(f"{question} [{hint}]: ").casefold()
            if not answer:
                return default
            if answer in {"y", "yes"}:
                return True
            if answer in {"n", "no"}:
                return False
            self._out.write("  Answer y or n.\n")


class UnattendedPrompter:
    interactive = False

    def ask(self, question: str, default: str | None = None, choices: tuple[str, ...] = ()) -> str:
        if default in (None, ""):
            raise SetupError(f"{question}: no value given; pass the matching flag when using --yes.")
        if choices and default not in choices:
            raise SetupError(f"{question}: {default!r} is not one of {', '.join(choices)}.")
        return default

    def confirm(self, question: str, default: bool = True) -> bool:
        return True
