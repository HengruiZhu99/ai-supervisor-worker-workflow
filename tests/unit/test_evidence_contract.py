from __future__ import annotations

import unittest

from aiflow.domain.evidence import EvidenceError, validate_cycle


def common() -> dict:
    return {
        "red": {"exit_code": 1, "discriminating": True},
        "green": {"exit_code": 0},
        "regression": {"exit_code": 0},
        "cold_review": {"status": "pass", "reviewer": "cold-self-review"},
        "attempts": 1,
        "questions": 0,
    }


class EvidenceContractTests(unittest.TestCase):
    def test_feature_bug_and_refactor_need_distinct_observable_evidence(self) -> None:
        feature = {**common(), "observable": "new --norm CLI result"}
        bug = {**common(), "reproduction": "zero vector produced NaN"}
        refactor = {
            **common(),
            "characterization": {"exit_code": 0, "discriminating": True},
            "behavior_equivalent": True,
        }
        self.assertEqual(validate_cycle("feature", feature)["status"], "VERIFIED")
        self.assertEqual(validate_cycle("bug", bug)["status"], "VERIFIED")
        self.assertEqual(validate_cycle("refactor", refactor)["status"], "VERIFIED")
        with self.assertRaises(EvidenceError):
            validate_cycle("bug", feature)

    def test_numerical_requires_units_shapes_reference_tolerance_and_convergence(
        self,
    ) -> None:
        evidence = {
            **common(),
            "reference": "analytic L2 norm",
            "oracle_provenance": "independent analytic identity",
            "units": "dimensionless",
            "dimensions": 3,
            "shapes": [[3], [16, 3]],
            "tolerance": {
                "absolute": 1e-12,
                "relative": 1e-10,
                "justification": "roundoff-scaled analytic comparison",
            },
            "convergence": {"levels": 3, "observed_order": 2.01, "minimum_order": 1.9},
            "deterministic_seed": 0,
        }
        self.assertEqual(validate_cycle("numerical", evidence)["kind"], "numerical")
        evidence["tolerance"] = {}
        with self.assertRaises(EvidenceError):
            validate_cycle("numerical", evidence)

    def test_performance_and_portability_guards_are_discriminating(self) -> None:
        performance = {
            **common(),
            "baseline_metric": 100.0,
            "candidate_metric": 102.0,
            "max_regression": 0.05,
            "metric": "milliseconds",
            "samples": 7,
            "direction": "lower-is-better",
            "warmups": 2,
            "comparability": "same input, executable, and resources",
            "equivalent_work": True,
            "output_equivalent": True,
        }
        portability = {
            **common(),
            "backends": {
                name: {
                    "status": "pass",
                    "dtype": "float64",
                    "layout": "contiguous",
                    "provenance": f"fixture:{name}",
                }
                for name in ("serial", "openmp", "cuda-build")
            },
        }
        self.assertEqual(
            validate_cycle("performance", performance)["status"], "VERIFIED"
        )
        self.assertEqual(
            validate_cycle("portability", portability)["status"], "VERIFIED"
        )
        performance["candidate_metric"] = 106.0
        with self.assertRaises(EvidenceError):
            validate_cycle("performance", performance)

    def test_retry_and_question_budgets_are_bounded(self) -> None:
        evidence = {**common(), "observable": "bounded feature", "attempts": 4}
        with self.assertRaises(EvidenceError):
            validate_cycle("feature", evidence)
        evidence.update(attempts=1, questions=3)
        with self.assertRaises(EvidenceError):
            validate_cycle("feature", evidence)


if __name__ == "__main__":
    unittest.main()
