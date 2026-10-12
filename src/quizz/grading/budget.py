"""Run SymPy work in a persistent worker process with a per-call time limit."""

import multiprocessing as mp
import threading

from quizz.checkers.equiv import Timeout

STARTUP_TIMEOUT = 60.0


def _worker(conn) -> None:
    import sympy  # noqa: F401  (warm the import before the first budgeted call)

    while True:
        try:
            fn, args = conn.recv()
        except (EOFError, OSError):
            return
        try:
            conn.send(("ok", fn(*args)))
        except BaseException as exc:  # report every failure; the caller maps it to Timeout
            conn.send(("err", f"{type(exc).__name__}: {exc}"))


def _ping() -> str:
    return "pong"


class WorkerRunner:
    """Callable runner: `runner(fn, *args, timeout=s)`. Kills and respawns the worker on timeout."""

    def __init__(self):
        self._ctx = mp.get_context("spawn")
        self._proc = None
        self._conn = None
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        if self._proc is not None and self._proc.is_alive():
            return
        parent, child = self._ctx.Pipe()
        proc = self._ctx.Process(target=_worker, args=(child,), daemon=True)
        proc.start()
        child.close()
        self._proc, self._conn = proc, parent
        parent.send((_ping, ()))
        if not parent.poll(STARTUP_TIMEOUT):
            self._kill()
            raise RuntimeError("grading worker failed to start")
        parent.recv()

    def _kill(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.join(5)
        if self._conn is not None:
            self._conn.close()
        self._proc = self._conn = None

    def __call__(self, fn, *args, timeout: float):
        with self._lock:
            self._ensure()
            self._conn.send((fn, args))
            if not self._conn.poll(timeout):
                self._kill()
                raise Timeout(f"{getattr(fn, '__name__', fn)} exceeded {timeout}s")
            status, value = self._conn.recv()
        if status == "err":
            raise Timeout(value)
        return value

    def close(self) -> None:
        with self._lock:
            self._kill()


_shared: WorkerRunner | None = None


def shared_runner() -> WorkerRunner:
    global _shared
    if _shared is None:
        _shared = WorkerRunner()
    return _shared
