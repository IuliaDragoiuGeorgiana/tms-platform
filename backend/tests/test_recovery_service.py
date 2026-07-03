import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.services.recovery_service import build_incident_recovery_analysis


def make_option(strategy: str, suffix: str, duration: float, cost: float) -> dict:
    return {
        "option_id": f"{strategy.lower()}_{suffix}",
        "type": strategy,
        "planned_date": "2026-07-04",
        "feasible": True,
        "recommended": False,
        "driver_id": f"driver-{suffix}",
        "vehicle_id": f"vehicle-{suffix}",
        "planned_km": duration / 10,
        "planned_duration_min": duration,
        "estimated_total_cost": cost,
        "late_orders_count": 0,
        "warnings": [],
        "route": [],
    }


class RecoveryAnalysisTests(unittest.TestCase):
    @patch("app.services.recovery_service.get_affected_orders_from_trip")
    @patch("app.services.recovery_service._build_route_recovery_analysis")
    def test_exposes_only_best_candidate_for_each_strategy(
        self,
        build_route_analysis,
        get_affected_orders,
    ):
        candidates = {
            "RECOVER_ALL_REMAINING": [
                make_option("RECOVER_ALL_REMAINING", "slow", 90, 100),
                make_option("RECOVER_ALL_REMAINING", "best", 60, 80),
            ],
            "RECOVER_PICKED_UP_ONLY": [
                make_option("RECOVER_PICKED_UP_ONLY", "slow", 70, 70),
                make_option("RECOVER_PICKED_UP_ONLY", "best", 40, 60),
            ],
            "POSTPONE_REMAINING": [
                make_option("POSTPONE_REMAINING", "slow", 80, 50),
                make_option("POSTPONE_REMAINING", "best", 50, 40),
            ],
        }

        def analysis_for_strategy(_db, _incident, strategy, **_kwargs):
            return {
                "incident_id": "incident",
                "options": candidates[strategy],
                "warnings": [],
            }

        build_route_analysis.side_effect = analysis_for_strategy
        order = SimpleNamespace(
            delivery_deadline=date(2026, 7, 5),
            earliest_delivery_date=date(2026, 7, 3),
            flexibility_days=2,
        )
        get_affected_orders.return_value = (
            {
                "unpicked": {
                    "order": order,
                    "has_pending_pickup": True,
                    "has_pending_delivery": True,
                },
                "picked": {
                    "order": order,
                    "has_pending_pickup": False,
                    "has_pending_delivery": True,
                },
            },
            [],
        )
        incident = SimpleNamespace(trip=SimpleNamespace(planned_date=date(2026, 7, 3)))

        result = build_incident_recovery_analysis(SimpleNamespace(), incident)

        self.assertEqual(len(result["options"]), 3)
        self.assertEqual(
            [option["option_id"] for option in result["options"]],
            [
                "recover_all_remaining_best",
                "recover_picked_up_only_best",
                "postpone_remaining_best",
            ],
        )
        self.assertEqual(
            sum(option["recommended"] for option in result["options"]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
