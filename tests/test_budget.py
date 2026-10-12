import time

import pytest
import sympy as sp

from quizz.checkers.equiv import Timeout
from quizz.grading.budget import WorkerRunner


@pytest.fixture(scope="module")
def runner():
    r = WorkerRunner()
    yield r
    r.close()


def test_worker_returns_results(runner):
    x = sp.Symbol("x")
    assert runner(sp.expand, (x + 1) ** 2, timeout=10) == x**2 + 2 * x + 1


def test_worker_times_out_then_recovers(runner):
    start = time.monotonic()
    with pytest.raises(Timeout):
        runner(time.sleep, 5, timeout=0.5)
    assert time.monotonic() - start < 3
    assert runner(abs, -3, timeout=10) == 3


def test_worker_errors_surface_as_timeout(runner):
    with pytest.raises(Timeout):
        runner(int, "not a number", timeout=10)
