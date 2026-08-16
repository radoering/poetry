from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import tomlkit

from poetry.toml.file import TOMLFile
from poetry.utils.env import PythonEnvsFile


if TYPE_CHECKING:
    from pathlib import Path

    from cleo.testers.command_tester import CommandTester
    from pytest_mock import MockerFixture

    from poetry.utils.env import MockEnv
    from tests.helpers import PoetryTestApplication
    from tests.types import CommandTesterFactory
    from tests.types import FakeVenvBuilder


@pytest.fixture
def venv_activate_37(venv_cache: Path, venv_name: str) -> None:
    envs_file = TOMLFile(venv_cache / "envs.toml")
    doc = tomlkit.document()
    doc[venv_name] = {"minor": "3.7", "patch": "3.7.0"}
    envs_file.write(doc)


@pytest.fixture
def tester(command_tester_factory: CommandTesterFactory) -> CommandTester:
    return command_tester_factory("env list")


def test_none_activated(
    tester: CommandTester,
    venvs_in_cache_dirs: list[str],
    mocker: MockerFixture,
    env: MockEnv,
) -> None:
    mocker.patch("poetry.utils.env.EnvManager.get", return_value=env)
    tester.execute()
    expected = "\n".join(venvs_in_cache_dirs)
    assert tester.io.fetch_output().strip() == expected


def test_activated(
    tester: CommandTester,
    venvs_in_cache_dirs: list[str],
    venv_cache: Path,
    venv_activate_37: None,
) -> None:
    tester.execute()
    expected = "\n".join(venvs_in_cache_dirs).replace("py3.7", "py3.7 (Activated)")
    assert tester.io.fetch_output().strip() == expected


def test_in_project_venv(
    tester: CommandTester, venvs_in_project_dir: list[str]
) -> None:
    tester.execute()
    expected = ".venv (Activated)\n"
    assert tester.io.fetch_output() == expected


def test_in_project_venv_no_explicit_config(
    tester: CommandTester, venvs_in_project_dir_none: list[str]
) -> None:
    tester.execute()
    expected = ".venv (Activated)\n"
    assert tester.io.fetch_output() == expected


def test_in_project_venv_is_false(
    tester: CommandTester, venvs_in_project_dir_false: list[str]
) -> None:
    tester.execute()
    expected = ""
    assert tester.io.fetch_output() == expected


def test_env_declared_in_python_envs_file_is_activated(
    tester: CommandTester,
    app: PoetryTestApplication,
    venvs_in_cache_dirs: list[str],
    venv_cache: Path,
    fake_venv: FakeVenvBuilder,
) -> None:
    declared = fake_venv(venv_cache / "declared")
    python_envs_file = PythonEnvsFile(
        app.poetry.file.path.parent / PythonEnvsFile.FILENAME
    )
    python_envs_file.path.write_text(f"{declared}\n", encoding="utf-8")

    tester.execute()

    expected = [*venvs_in_cache_dirs, f"{declared} (Activated)"]
    assert tester.io.fetch_output().strip() == "\n".join(expected)
