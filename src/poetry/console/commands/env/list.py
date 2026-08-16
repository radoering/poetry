from __future__ import annotations

from typing import TYPE_CHECKING
from typing import ClassVar

from cleo.helpers import option

from poetry.console.commands.command import Command


if TYPE_CHECKING:
    from cleo.io.inputs.option import Option


class EnvListCommand(Command):
    name = "env list"
    description = "Lists all virtualenvs associated with the current project."

    options: ClassVar[list[Option]] = [
        option("full-path", None, "Output the full paths of the virtualenvs.")
    ]

    def handle(self) -> int:
        from poetry.utils.env import EnvManager

        manager = EnvManager(self.poetry, io=self.io)
        current_env = manager.get()

        envs = manager.list()
        for venv in envs:
            name = venv.path.name
            if self.option("full-path"):
                name = str(venv.path)

            if venv == current_env:
                self.line(f"<info>{name} (Activated)</info>")

                continue

            self.line(name)

        if current_env not in envs and current_env.path == (
            manager.get_python_envs_file_default()
        ):
            # The current environment is declared in the ".python-envs" file
            # but not managed by Poetry, so it is not part of the list above.
            self.line(f"<info>{current_env.path} (Activated)</info>")

        return 0
