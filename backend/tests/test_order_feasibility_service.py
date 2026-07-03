from app.services.order_feasibility_service import check_order_operational_warnings
from tests.helpers import make_order


def test_operational_warnings_flag_risky_orders_only():
    risky_order = make_order(type_marfa="ADR", priority="CRITIC")
    risky_warnings = check_order_operational_warnings(risky_order)

    assert any("ADR" in warning for warning in risky_warnings)
    assert any("CRITIC" in warning for warning in risky_warnings)

    standard_order = make_order(type_marfa="STANDARD", priority="NORMAL")
    assert check_order_operational_warnings(standard_order) == []
