"""What the AI Note Taker is doing, for the course page: its todo list and its actions.

The tools report their own actions (deepagents does not pass callbacks into subagents, so a
callback would see only the main agent). Saved on the run's `sync_runs` row after every change;
a failed save is printed and ignored, so progress never stops a run.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

# Only the latest actions are kept; older ones scroll away on the page anyway.
MAX_ACTIONS = 40

Save = Callable[[list[dict[str, Any]], list[dict[str, Any]], str | None], None]


@dataclass
class Action:
    text: str
    status: str = "running"  # running | done | failed
    detail: str = ""


@dataclass
class Progress:
    """Records the agent's progress and saves it with `save(todos, actions, step)`."""

    save: Save | None = None
    todo_list: list[dict[str, str]] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)

    def set_todos(self, todos: list[dict[str, Any]]) -> None:
        self.todo_list = [
            {"content": str(t.get("content", "")), "status": str(t.get("status", "pending"))}
            for t in todos
            if isinstance(t, dict)
        ]
        self.flush()

    @contextmanager
    def action(self, text: str) -> Iterator[Action]:
        """One step the page shows as running, then done (with `detail`) or failed."""
        entry = Action(text)
        self.actions = [*self.actions, entry][-MAX_ACTIONS:]
        self.flush()
        try:
            yield entry
        except Exception as error:
            entry.status = "failed"
            entry.detail = entry.detail or str(error)
            self.flush()
            raise
        entry.status = "failed" if entry.status == "failed" else "done"
        self.flush()

    def note(self, text: str, detail: str = "") -> None:
        """A finished step, such as handing work to a subagent."""
        self.actions = [*self.actions, Action(text, "done", detail)][-MAX_ACTIONS:]
        self.flush()

    def step(self) -> str | None:
        running = [a.text for a in self.actions if a.status == "running"]
        if running:
            return running[-1]
        active = [t["content"] for t in self.todo_list if t["status"] == "in_progress"]
        return active[0] if active else None

    def flush(self) -> None:
        if self.save is None:
            return
        try:
            self.save(
                self.todo_list,
                [{"text": a.text, "status": a.status, "detail": a.detail} for a in self.actions],
                self.step(),
            )
        except Exception as error:
            print(f"Could not save the Note Taker progress: {error!r}")
