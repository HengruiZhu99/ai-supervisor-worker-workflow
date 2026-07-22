from __future__ import annotations

import unittest
from pathlib import Path

from aiflow.scheduler.readonly import ReadOnlyScheduler, SchedulerError


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "schedulers"
SLURM = (FIXTURES / "slurm_squeue.txt").read_text()
PBS = (FIXTURES / "pbs_qstat.txt").read_text()


class SchedulerTests(unittest.TestCase):
    def test_slurm_and_pbs_fixtures_are_parsed_without_mutation(self) -> None:
        slurm = ReadOnlyScheduler("slurm", min_interval=5)
        pbs = ReadOnlyScheduler("pbs", min_interval=5)
        self.assertEqual(slurm.parse(SLURM)[0]["state"], "RUNNING")
        self.assertEqual(slurm.parse(SLURM)[1]["reason_or_node"], "(Priority)")
        self.assertEqual(pbs.parse(PBS)[0]["job_id"], "101.server")
        self.assertEqual(pbs.parse(PBS)[1]["state"], "QUEUED")
        self.assertEqual(slurm.command(user="alice")[0], "squeue")
        self.assertEqual(pbs.command(user="alice")[0], "qstat")

    def test_mutating_scheduler_actions_are_not_exposed(self) -> None:
        scheduler = ReadOnlyScheduler("slurm")
        for command in ("scancel", "scontrol", "sbatch", "qdel", "qsub"):
            with self.subTest(command=command), self.assertRaises(SchedulerError):
                scheduler.validate_command((command, "123"))
        with self.assertRaises(SchedulerError):
            ReadOnlyScheduler("unknown")

    def test_monitoring_is_rate_limited_and_cached(self) -> None:
        calls = []

        def runner(command):
            calls.append(command)
            return SLURM

        scheduler = ReadOnlyScheduler("slurm", min_interval=30, runner=runner)
        first = scheduler.snapshot(user="alice", now=100.0)
        second = scheduler.snapshot(user="alice", now=101.0)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
