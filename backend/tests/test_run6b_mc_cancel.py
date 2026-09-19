"""Run 6b: Monte Carlo job cancellation (service + route)."""

import json
import threading
import time
from pathlib import Path

from app.services import monte_carlo

_FIXTURE = Path(__file__).parent / "fixtures" / "analytic_acquisition.json"
_DRIVER = {"inputPath": "exitCapRatePct", "distribution": "uniform",
           "params": {"min": 0.05, "max": 0.06}}


def _values() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _wait(job_id: str, until: set[str], timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    status = monte_carlo.job_status(job_id)
    while status is not None and status["status"] not in until and time.time() < deadline:
        time.sleep(0.02)
        status = monte_carlo.job_status(job_id)
    assert status is not None
    return status


def test_cancel_stops_a_running_job_after_the_trial_in_flight(monkeypatch):
    # Slow every trial down so the job is still running when we cancel.
    real_compute = monte_carlo.engine.compute
    gate = threading.Event()

    def slow_compute(values):
        gate.wait(0.05)
        return real_compute(values)

    monkeypatch.setattr(monte_carlo.engine, "compute", slow_compute)
    job_id = monte_carlo.start_job(_values(), [_DRIVER], None, 400, 7, 0.08)
    _wait(job_id, until=set(), timeout=0.3)  # let a few trials run
    assert monte_carlo.cancel_job(job_id) == "cancelling"
    status = _wait(job_id, until={"cancelled", "done", "failed"})
    assert status["status"] == "cancelled"
    assert status["completed"] < 400
    assert "result" not in status
    # Idempotent: cancelling again reports the terminal status.
    assert monte_carlo.cancel_job(job_id) == "cancelled"
    assert monte_carlo.pending_jobs() == 0


def test_cancel_of_a_finished_job_reports_done():
    job_id = monte_carlo.start_job(_values(), [_DRIVER], None, 5, 3, 0.08)
    status = _wait(job_id, until={"done", "failed"})
    assert status["status"] == "done"
    assert monte_carlo.cancel_job(job_id) == "done"
    assert monte_carlo.cancel_job("nope") is None


def test_cancel_route(client):
    started = client.post("/api/compute/monte-carlo", json={
        "values": _values(), "n": 5, "seed": 1, "drivers": [_DRIVER],
    }).json()
    job_id = started["jobId"]
    _wait(job_id, until={"done", "failed"})
    res = client.delete(f"/api/compute/monte-carlo/{job_id}")
    assert res.status_code == 200
    assert res.json() == {"jobId": job_id, "status": "done"}
    assert client.delete("/api/compute/monte-carlo/unknown").status_code == 404
