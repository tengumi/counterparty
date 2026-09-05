"""Filesystem boundary of the Deep Agents harness (Specs 04 §4).

Deep Agents ships the file tools; this module only says *where they may point*.
Three independent limits apply, so none of them is load-bearing alone:

1. the backend is ``StateBackend`` — virtual files kept in the LangGraph
   checkpoint of one thread. There is no OS root behind it, so no path can
   reach the host disk, another project's storage or a process environment;
2. the supported ``FilesystemPermission`` rules pin every file tool to the
   workspace of exactly one ``(project_id, thread_id)`` pair and deny the rest
   of the virtual tree. Enforcement happens inside the framework's own
   ``FilesystemMiddleware``; this service writes no path router of its own;
3. ``StateBackend`` is not a sandbox backend, so the ``execute`` tool has no
   shell to run against and refuses every command.

Rules are evaluated first-match-wins, so the allow rule for the current thread
must precede the catch-all deny.
"""

from uuid import UUID

from deepagents.middleware.filesystem import FilesystemPermission

_ROOT = "/projects"

DENIED_PATH_EXAMPLES: tuple[str, ...] = (
    "/etc/passwd",
    "/proc/self/environ",
    "/projects/other-project/threads/other-thread/notes.md",
)
"""Paths the deny rule must refuse; used by the boundary test as documentation."""


def thread_workspace_root(project_id: UUID, thread_id: UUID) -> str:
    """Return the only directory this thread's file tools may address."""
    return f"{_ROOT}/{project_id}/threads/{thread_id}"


def scoped_permissions(project_id: UUID, thread_id: UUID) -> list[FilesystemPermission]:
    """Allow one thread workspace and deny every other virtual path."""
    root = thread_workspace_root(project_id, thread_id)
    return [
        FilesystemPermission(
            operations=["read", "write"], paths=[root, f"{root}/**"], mode="allow"
        ),
        FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
    ]
