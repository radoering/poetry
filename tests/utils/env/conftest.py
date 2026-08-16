from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cleo.io.buffered_io import BufferedIO

from poetry.utils.env import EnvManager
from poetry.utils.env import PythonEnvsFile


if TYPE_CHECKING:
    from poetry.poetry import Poetry
    from tests.types import FixtureDirGetter
    from tests.types import ProjectFactory
    from tests.types import PythonEnvsFileWriter


@pytest.fixture
def poetry(project_factory: ProjectFactory, fixture_dir: FixtureDirGetter) -> Poetry:
    return project_factory("simple", source=fixture_dir("simple_project"))


@pytest.fixture
def io() -> BufferedIO:
    return BufferedIO()


@pytest.fixture
def manager(poetry: Poetry, io: BufferedIO) -> EnvManager:
    return EnvManager(poetry, io)


@pytest.fixture
def python_envs_file(poetry: Poetry) -> PythonEnvsFile:
    return PythonEnvsFile(poetry.file.path.parent / PythonEnvsFile.FILENAME)


@pytest.fixture
def write_python_envs(python_envs_file: PythonEnvsFile) -> PythonEnvsFileWriter:
    def write(content: str) -> PythonEnvsFile:
        python_envs_file.path.write_text(content, encoding="utf-8", newline="")
        return python_envs_file

    return write
