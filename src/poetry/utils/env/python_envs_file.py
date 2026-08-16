from __future__ import annotations

import os

from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable


class PythonEnvsFile:
    """
    A ``.python-envs`` file as specified in PEP 832.

    The file lives in the root of a project directory and contains one
    environment per line. Paths may be relative, in which case they are
    relative to the directory containing the file. The last environment listed
    is considered the default environment.

    Lines that are empty or start with "#" are ignored, but they are preserved
    when the file is rewritten, as are entries written by other tools.
    """

    FILENAME = ".python-envs"

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    @property
    def project_dir(self) -> Path:
        return self._path.parent

    def exists(self) -> bool:
        return self._path.is_file()

    def read(self) -> list[Path]:
        """
        Return the environments declared in the file, in the order they appear.

        The last entry is the default environment. Duplicates are not removed
        because they carry no meaning.
        """
        return [path for _, path in self._read_lines() if path is not None]

    def add(self, env_path: Path) -> None:
        """
        Append an environment to the file unless it is already declared.
        """
        lines = self._read_lines()
        key = self._key(env_path)
        if any(path is not None and self._key(path) == key for _, path in lines):
            return

        self._write_lines([*lines, (self._render(env_path), env_path)])

    def promote(self, env_path: Path) -> None:
        """
        Make an environment the default one by moving it to the last position,
        adding it if it is not declared yet.
        """
        key = self._key(env_path)
        lines = [
            line
            for line in self._read_lines()
            if line[1] is None or self._key(line[1]) != key
        ]

        self._write_lines([*lines, (self._render(env_path), env_path)])

    def remove(self, env_path: Path) -> None:
        """
        Remove all entries pointing to an environment.
        """
        key = self._key(env_path)
        self.remove_matching(lambda path: self._key(path) == key)

    def remove_matching(self, predicate: Callable[[Path], bool]) -> None:
        """
        Remove all entries whose (resolved) path matches the given predicate.
        """
        lines = self._read_lines()
        remaining = [
            line for line in lines if line[1] is None or not predicate(line[1])
        ]
        if len(remaining) != len(lines):
            self._write_lines(remaining)

    def _read_lines(self) -> list[tuple[str, Path | None]]:
        """
        Return all lines of the file as (raw line, environment path) tuples.

        The path is None for lines that do not declare an environment, i.e.
        empty lines and comments. Such lines are kept so that they can be
        preserved when the file is rewritten.
        """
        if not self.exists():
            return []

        lines: list[tuple[str, Path | None]] = []
        # splitlines() handles both "\n" and "\r\n" and ignores a trailing newline
        for raw_line in self._path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                lines.append((raw_line, None))
                continue

            path = Path(line)
            if not path.is_absolute():
                path = self.project_dir / path
            lines.append((raw_line, path))

        return lines

    def _write_lines(self, lines: list[tuple[str, Path | None]]) -> None:
        if not lines:
            self._path.unlink(missing_ok=True)
            return

        content = "".join(f"{raw_line}\n" for raw_line, _ in lines)
        if self.exists() and self._path.read_text(encoding="utf-8") == content:
            # nothing to do, do not touch the file
            return

        self._path.write_text(content, encoding="utf-8", newline="\n")

    def _render(self, env_path: Path) -> str:
        """
        Render an environment path as it should be written to the file.

        Environments inside the project directory are written as relative paths
        so that the file stays portable, all others as absolute paths.
        """
        try:
            return env_path.relative_to(self.project_dir).as_posix()
        except ValueError:
            return str(env_path)

    @staticmethod
    def _key(path: Path) -> str:
        """
        Normalized representation of a path used to compare entries.

        os.path.realpath() is a pure normalization for paths that do not exist,
        so stale entries can still be matched.
        """
        return os.path.normcase(os.path.realpath(path))
