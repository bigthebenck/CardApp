"""Runs X to Y searches in a separate process, so they can't slow the window down.

A search spends most of its time in plain Python loops. On a thread those hold
the interpreter lock and the window stutters while it runs; in its own process
it doesn't, a cancel or closed tab can stop it outright, and the memory a deep
search used is handed back the moment it ends.

Each process runs one search and then exits. Starting one takes a few tenths of
a second, so a spare is kept started and waiting (``warm_up``); a search takes
it (``take``) and the next spare is started once that search is over. The
worker only imports the toolkit-independent model, never Qt.
"""

import multiprocessing as mp
import queue

from .. import path_finder
from .model import search_outcome

_ctx = mp.get_context("spawn")  # the same on every platform; fork would copy Qt's state
_spare = None


def _serve(jobs, results, cancel):
    """The worker process: wait for one search, run it, report back, exit."""
    try:
        job = jobs.get()
    except (EOFError, OSError, KeyboardInterrupt):
        return
    if job is None:
        return
    start, end, depth = job
    try:
        outcome = search_outcome(start, end, depth, cancel.is_set,
                                 lambda f, text: results.put(("progress", (f, text))),
                                 lambda best: results.put(("best", best)))
        results.put(("done", outcome))
    except path_finder.SearchCancelled:
        results.put(("cancelled", None))
    except Exception as exc:  # shown in the window instead of dying silently
        results.put(("error", f"{exc}" or type(exc).__name__))


class Worker:
    """One started process, waiting for its search."""

    def __init__(self):
        self.jobs = _ctx.Queue()
        self.results = _ctx.Queue()
        self.cancel = _ctx.Event()
        self.process = _ctx.Process(target=_serve, args=(self.jobs, self.results, self.cancel),
                                    daemon=True, name="CardApp search")
        self.process.start()

    def usable(self):
        return self.process.is_alive() and not self.cancel.is_set()

    def run(self, start, end, depth):
        self.jobs.put((list(start), list(end), depth))

    def messages(self):
        """Everything the worker sent since the last call, oldest first."""
        out = []
        while True:
            try:
                out.append(self.results.get_nowait())
            except (queue.Empty, EOFError, OSError):
                return out

    def alive(self):
        return self.process.is_alive()

    def stop(self):
        """End the process now, whatever it is doing."""
        self.cancel.set()
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=1)
        for q in (self.jobs, self.results):
            q.cancel_join_thread()
            q.close()


def warm_up():
    """Start a spare process if none is waiting, so the next search starts at once."""
    global _spare
    if _spare is None or not _spare.usable():
        _spare = Worker()


def take():
    """A started process for one search: the spare if there is one, else a new one."""
    global _spare
    worker, _spare = _spare, None
    if worker is None or not worker.usable():
        worker = Worker()
    return worker


def shutdown():
    """Stop the spare (running searches are stopped by their tabs)."""
    global _spare
    if _spare is not None:
        _spare.stop()
        _spare = None
