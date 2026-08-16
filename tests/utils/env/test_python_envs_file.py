from __future__ import annotations

import os

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from poetry.utils.env import PythonEnvsFile


if TYPE_CHECKING:
    from tests.types import PythonEnvsFileWriter


@pytest.fixture
def python_envs_file(tmp_path: Path) -> PythonEnvsFile:
    return PythonEnvsFile(tmp_path / PythonEnvsFile.FILENAME)


@pytest.fixture
def write_python_envs(python_envs_file: PythonEnvsFile) -> PythonEnvsFileWriter:
    def write(content: str) -> PythonEnvsFile:
        python_envs_file.path.write_text(content, encoding="utf-8", newline="")
        return python_envs_file

    return write


def test_missing_file(python_envs_file: PythonEnvsFile) -> None:
    assert not python_envs_file.exists()
    assert python_envs_file.read() == []


@pytest.mark.parametrize(
    "content",
    [
        "/foo\n/bar\n",
        "/foo\n/bar",
        "/foo\r\n/bar\r\n",
        "/foo\n\n/bar\n\n",
        "# a comment\n/foo\n  \n/bar\n",
    ],
)
def test_read(
    write_python_envs: PythonEnvsFileWriter, tmp_path: Path, content: str
) -> None:
    python_envs_file = write_python_envs(content)

    assert python_envs_file.read() == [Path("/foo"), Path("/bar")]


def test_read_resolves_relative_paths(
    write_python_envs: PythonEnvsFileWriter, tmp_path: Path
) -> None:
    python_envs_file = write_python_envs("/abs/env\n.venv\nenvs/other\n")

    assert python_envs_file.read() == [
        Path("/abs/env"),
        tmp_path / ".venv",
        tmp_path / "envs" / "other",
    ]


def test_read_keeps_duplicates(write_python_envs: PythonEnvsFileWriter) -> None:
    python_envs_file = write_python_envs("/foo\n/bar\n/foo\n")

    assert python_envs_file.read() == [Path("/foo"), Path("/bar"), Path("/foo")]


def test_add_creates_file(python_envs_file: PythonEnvsFile) -> None:
    python_envs_file.add(Path("/foo"))

    assert python_envs_file.path.read_text(encoding="utf-8") == "/foo\n"


def test_add_appends(write_python_envs: PythonEnvsFileWriter) -> None:
    python_envs_file = write_python_envs("/foo\n")

    python_envs_file.add(Path("/bar"))

    assert python_envs_file.read() == [Path("/foo"), Path("/bar")]


def test_add_does_not_touch_file_if_already_present(
    write_python_envs: PythonEnvsFileWriter,
) -> None:
    python_envs_file = write_python_envs("/foo\n/bar\n")
    mtime = python_envs_file.path.stat().st_mtime_ns

    python_envs_file.add(Path("/foo"))

    assert python_envs_file.path.read_text(encoding="utf-8") == "/foo\n/bar\n"
    assert python_envs_file.path.stat().st_mtime_ns == mtime


def test_add_writes_relative_path_inside_project(
    python_envs_file: PythonEnvsFile, tmp_path: Path
) -> None:
    python_envs_file.add(tmp_path / "envs" / "some-env")

    assert python_envs_file.path.read_text(encoding="utf-8") == "envs/some-env\n"


def test_promote_creates_file(python_envs_file: PythonEnvsFile) -> None:
    python_envs_file.promote(Path("/foo"))

    assert python_envs_file.read() == [Path("/foo")]


def test_promote_moves_entry_to_last_position(
    write_python_envs: PythonEnvsFileWriter,
) -> None:
    python_envs_file = write_python_envs("/foo\n/bar\n/baz\n")

    python_envs_file.promote(Path("/foo"))

    assert python_envs_file.read() == [Path("/bar"), Path("/baz"), Path("/foo")]


def test_promote_collapses_duplicates(write_python_envs: PythonEnvsFileWriter) -> None:
    python_envs_file = write_python_envs("/foo\n/bar\n/foo\n")

    python_envs_file.promote(Path("/foo"))

    assert python_envs_file.read() == [Path("/bar"), Path("/foo")]


def test_promote_does_not_touch_file_if_already_last(
    write_python_envs: PythonEnvsFileWriter,
) -> None:
    python_envs_file = write_python_envs("/foo\n/bar\n")
    mtime = python_envs_file.path.stat().st_mtime_ns

    python_envs_file.promote(Path("/bar"))

    assert python_envs_file.path.stat().st_mtime_ns == mtime


def test_remove_drops_all_duplicates(write_python_envs: PythonEnvsFileWriter) -> None:
    python_envs_file = write_python_envs("/foo\n/bar\n/foo\n")

    python_envs_file.remove(Path("/foo"))

    assert python_envs_file.read() == [Path("/bar")]


def test_remove_relative_entry(
    write_python_envs: PythonEnvsFileWriter, tmp_path: Path
) -> None:
    python_envs_file = write_python_envs("envs/other\n/bar\n")

    python_envs_file.remove(tmp_path / "envs" / "other")

    assert python_envs_file.read() == [Path("/bar")]


def test_remove_unknown_entry_does_not_touch_file(
    write_python_envs: PythonEnvsFileWriter,
) -> None:
    python_envs_file = write_python_envs("/foo\n/bar\n")
    mtime = python_envs_file.path.stat().st_mtime_ns

    python_envs_file.remove(Path("/baz"))

    assert python_envs_file.path.stat().st_mtime_ns == mtime


def test_remove_last_entry_deletes_file(
    write_python_envs: PythonEnvsFileWriter,
) -> None:
    python_envs_file = write_python_envs("/foo\n")

    python_envs_file.remove(Path("/foo"))

    assert not python_envs_file.exists()


def test_remove_matching(write_python_envs: PythonEnvsFileWriter) -> None:
    python_envs_file = write_python_envs("/envs/foo-py3.8\n/other\n/envs/foo-py3.9\n")

    python_envs_file.remove_matching(lambda path: path.name.startswith("foo-"))

    assert python_envs_file.read() == [Path("/other")]


def test_write_preserves_foreign_lines(
    write_python_envs: PythonEnvsFileWriter,
) -> None:
    python_envs_file = write_python_envs(
        "# managed by another tool\nsome/relative/env\n\n/foo\n"
    )

    python_envs_file.promote(Path("/bar"))

    assert python_envs_file.path.read_text(encoding="utf-8") == (
        "# managed by another tool\nsome/relative/env\n\n/foo\n/bar\n"
    )


@pytest.mark.skipif(
    os.path.normcase("A") == "A", reason="requires a case-insensitive file system"
)
def test_entries_are_matched_case_insensitively(
    write_python_envs: PythonEnvsFileWriter,
) -> None:
    python_envs_file = write_python_envs("/Foo\n/bar\n")

    python_envs_file.remove(Path("/foo"))

    assert python_envs_file.read() == [Path("/bar")]


def test_entries_are_matched_through_symlinks(
    write_python_envs: PythonEnvsFileWriter, tmp_path: Path
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)

    python_envs_file = write_python_envs(f"{link}\n")

    python_envs_file.promote(target)

    assert python_envs_file.read() == [target]
