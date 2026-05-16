"""Builtin package uninstaller.

Entry point is the ``uninstall_distribution`` function.

Adapted from pip's ``pip._internal.req.req_uninstall`` so Poetry can uninstall
packages without invoking ``pip uninstall`` as a subprocess. The module is
self-contained and does not import from pip.

Most methods and classes are borrowed from pip with minimal adaptations.
The env-prefix and stdlib guards that pip applies in
``UninstallPathSet.from_dist`` have been moved to ``uninstall_distribution``,
along with all legacy-install branches (setuptools flat installs,
easy_install eggs, develop-egg links) being dropped entirely - Poetry should
only see modern ``.dist-info`` installs.

Unlike pip, this uninstaller removes files directly instead of stashing them
for a possible rollback: it raises if a file cannot be removed (a file that is
already missing is fine) and removes the ``.dist-info`` directory last, so that
a failed, aborted uninstall can simply be triggered again - the ``RECORD`` file
inside ``.dist-info`` is what tells us which files to remove.

ATTENTION: Do not convert os.path to pathlib lightly in this module!
    pathlib is often slower and some path operations
    are called for each file that has to be removed.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Iterator
    from importlib import metadata
    from importlib.metadata import PackagePath
    from pathlib import Path

    from poetry.utils.env import Env


logger = logging.getLogger(__name__)


def _normalize_path(path: str | Path, resolve_symlinks: bool = True) -> str:
    path = os.path.expanduser(path)
    path = os.path.realpath(path) if resolve_symlinks else os.path.abspath(path)
    return os.path.normcase(path)


def _safe_listdir(path: str) -> tuple[str, ...]:
    """Return directory entries (empty if it is missing or not a directory)."""
    try:
        return tuple(os.listdir(path))
    except OSError:
        return ()


def _uninstallation_paths(
    dist_files: list[PackagePath], location: str | Path
) -> Iterator[str]:
    """Yield all uninstallation paths declared in the distribution's RECORD.

    For each .py file in RECORD, also yield the sibling .pyc/.pyo. The
    ``UninstallPathSet.add`` method handles ``__pycache__`` discovery.
    """
    for entry in dist_files:
        path = os.path.join(location, str(entry))
        yield path
        if path.endswith(".py"):
            dn, fn = os.path.split(path)
            base = fn[:-3]
            yield os.path.join(dn, base + ".pyc")
            yield os.path.join(dn, base + ".pyo")


def compress_for_removal(paths: Iterable[str]) -> set[str]:
    """Returns a set containing the paths that need to be removed.

    This set may include directories when the original sequence of paths
    included every file on disk, so they can be removed in a single rmtree.
    """
    case_map = {os.path.normcase(p): p for p in paths}
    remaining = set(case_map)
    unchecked = sorted({os.path.split(p)[0] for p in case_map.values()}, key=len)
    wildcards: set[str] = set()

    def norm_join(*a: str) -> str:
        return os.path.normcase(os.path.join(*a))

    for root in unchecked:
        if any(os.path.normcase(root).startswith(w) for w in wildcards):
            # This directory has already been handled.
            continue

        all_files: set[str] = set()
        all_subdirs: set[str] = set()
        for dirname, subdirs, files in os.walk(root):
            all_subdirs.update(norm_join(root, dirname, d) for d in subdirs)
            all_files.update(norm_join(root, dirname, f) for f in files)
        # If all the files we found are in our remaining set of files to
        # remove, then remove them from the latter set and add a wildcard
        # for the directory.
        if not (all_files - remaining):
            remaining.difference_update(all_files)
            remaining.difference_update(all_subdirs)
            wildcards.add(root + os.sep)

    return set(map(case_map.__getitem__, remaining)) | wildcards


class UninstallPathSet:
    """A set of file paths to be removed when uninstalling a distribution."""

    def __init__(self, dist: metadata.Distribution, env_path: Path) -> None:
        self._paths: set[str] = set()
        self._refuse: set[str] = set()
        # Read identifying metadata eagerly so log messages still work after
        # remove() deletes the .dist-info directory.
        self._dist_name = dist.name
        self._dist_version = dist.metadata["Version"]
        # Append os.sep so the startswith() check in _permitted() does not
        # spuriously match a sibling directory whose name starts with env_path
        # (e.g. env_path="/tmp/.venv" would otherwise match "/tmp/.venv-other").
        self._env_prefix = _normalize_path(env_path) + os.sep
        # Create local cache of normalize_path results. Creating an UninstallPathSet
        # can result in hundreds/thousands of redundant calls to normalize_path with
        # the same args, which hurts performance.
        self._normalize_path_cached = functools.lru_cache(maxsize=None)(_normalize_path)
        # Cache __pycache__ listings so a directory is scanned only once even
        # though add() is called for every .py file it contains. This is safe
        # because we are robust against files that may have been deleted
        # in the meantime.
        self._listdir_cached = functools.lru_cache(maxsize=None)(_safe_listdir)
        # Normalized path of the .dist-info directory, so remove() can delete it
        # last (see remove() for why).
        dist_info_path: Path = dist._path  # type: ignore[attr-defined]
        self._dist_info = self._normalize_path_cached(str(dist_info_path))

    @property
    def paths(self) -> set[str]:
        return self._paths

    @property
    def refused(self) -> set[str]:
        return self._refuse

    def _permitted(self, path: str) -> bool:
        """Return True if ``path`` is inside the env prefix."""
        return path.startswith(self._env_prefix)

    def add(self, path: str | Path) -> None:
        head, tail = os.path.split(path)

        # We normalize the head to resolve parent directory symlinks, but not
        # the tail, since we only want to uninstall symlinks, not their targets.
        norm_path = os.path.join(
            self._normalize_path_cached(head), os.path.normcase(tail)
        )

        if not os.path.exists(norm_path):
            return
        if self._permitted(norm_path):
            self._paths.add(norm_path)
        else:
            self._refuse.add(norm_path)

        # ``__pycache__`` bytecode may not be listed in RECORD (it is often
        # compiled lazily on first import). Discover it for every source file.
        if os.path.splitext(norm_path)[1] == ".py":
            for pyc in self._pycache_files(norm_path):
                self.add(pyc)

    def _pycache_files(self, py_path: str) -> Iterator[str]:
        """Yield bytecode cache files for a source ``.py`` file.

        Bytecode lives in a sibling ``__pycache__`` directory named
        ``<stem>.<tag>.pyc`` (PEP 3147), where ``<tag>`` identifies the Python
        version/implementation that compiled it. The target environment may run
        a different Python version than the interpreter executing Poetry, so we
        match bytecode compiled for *any* version - not just the current
        interpreter's ``cache_from_source`` tag.

        The directory listing is memoized (``_listdir_cached``) so that a
        ``__pycache__`` is scanned only once even when many ``.py`` files in the
        same directory each trigger this lookup.
        """
        head, tail = os.path.split(py_path)
        pycache = os.path.join(head, "__pycache__")
        # ``tail`` is already normcased by the caller; match case-insensitively
        # against the on-disk names for Windows.
        prefix = os.path.normcase(tail[: -len(".py")]) + "."
        for name in self._listdir_cached(pycache):
            norm_name = os.path.normcase(name)
            if norm_name.startswith(prefix) and norm_name.endswith((".pyc", ".pyo")):
                yield os.path.join(pycache, name)

    def remove(self) -> None:
        """Remove every path, deleting the .dist-info directory last.

        Files are removed directly. A path that cannot be removed raises; a
        path that is already missing is ignored. The .dist-info directory is
        removed last so that, if removal fails partway through, the uninstall
        can simply be triggered again - its RECORD is what tells us which files
        to remove.
        """
        if not self._paths:
            logger.warning(
                "Cannot uninstall '%s'. No files were found to uninstall.",
                self._dist_name,
            )
            return

        logger.debug("Uninstalling %s %s.", self._dist_name, self._dist_version)

        for_removal = compress_for_removal(self._paths)

        dist_info_paths = {p for p in for_removal if self._is_dist_info(p)}
        other_paths = for_removal - dist_info_paths

        # Remove everything but the .dist-info directory first, then .dist-info.
        for path in sorted(other_paths) + sorted(dist_info_paths):
            logger.debug("Removing file or directory %s", path)
            self._remove_path(path)

        logger.debug(
            "Successfully uninstalled %s %s", self._dist_name, self._dist_version
        )

    def _is_dist_info(self, path: str) -> bool:
        """Return True if ``path`` is the .dist-info directory or inside it."""
        norm = os.path.normcase(path.rstrip(os.sep))
        return norm == self._dist_info or norm.startswith(self._dist_info + os.sep)

    @staticmethod
    def _remove_path(path: str) -> None:
        """Remove a file or directory.

        An already-missing path is ignored; any other failure propagates so the
        caller can abort the operation.
        """
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                # ``path`` may be a collapsed directory wildcard from
                # compress_for_removal(); remove the whole tree at once.
                shutil.rmtree(path)
            else:
                # Files and symlinks (unlink the link, not its target).
                os.remove(path)
        except FileNotFoundError:
            # Already gone - nothing to do.
            pass


def uninstall_distribution(env: Env, package_name: str) -> UninstallPathSet | None:
    """Uninstall ``package_name`` from ``env``.

    Removes the package's files immediately (the .dist-info directory last).
    Raises if a file cannot be removed. Returns the pathset (useful for
    inspection/logging), or ``None`` if there was nothing to uninstall (package
    not installed, located outside the env, in the stdlib, or missing RECORD).
    """
    dist = next(iter(env.site_packages.distributions(name=package_name)), None)

    if dist is None:
        logger.warning("Skipping %s as it is not installed.", package_name)
        return None

    logger.debug("Found existing installation: %s", package_name)

    dist_info_path: Path = dist._path  # type: ignore[attr-defined]
    dist_parent = dist_info_path.parent

    # Normalize through _normalize_path (realpath + normcase) so these guards
    # resolve symlinks and case exactly the way UninstallPathSet._permitted()
    # does - otherwise a symlinked venv prefix could pass one check but fail the
    # other.
    norm_dist_parent = _normalize_path(dist_parent)
    norm_env_prefix = _normalize_path(env.path)

    # Append os.sep so a sibling directory whose name merely starts with the env
    # prefix (e.g. "/tmp/.venv-other" vs "/tmp/.venv") is not treated as inside.
    if not (
        norm_dist_parent == norm_env_prefix
        or norm_dist_parent.startswith(norm_env_prefix + os.sep)
    ):
        logger.error(
            "Not uninstalling %s at %s, outside environment %s",
            dist.name,
            dist_parent,
            env.path,
        )
        return None

    stdlib_paths = {
        _normalize_path(p)
        for p in {env.paths.get("stdlib"), env.paths.get("platstdlib")}
        if p
    }
    if norm_dist_parent in stdlib_paths:
        logger.error(
            "Not uninstalling %s at %s, as it is in the standard library.",
            dist.name,
            dist_parent,
        )
        return None

    dist_files = dist.files
    if dist_files is None:
        logger.error(
            "Cannot uninstall %s: RECORD file is missing or unreadable.",
            dist.name,
        )
        return None

    path_set = UninstallPathSet(dist, env.path)
    for path in _uninstallation_paths(dist_files, dist_parent):
        path_set.add(path)

    path_set.remove()

    return path_set
