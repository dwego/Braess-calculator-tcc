import pytest

from braess.costs import BPRCost, LinearCost


def test_linear_cost_without_congestion() -> None:
    cost = LinearCost(alpha=45.0, beta=0.0)

    assert cost.travel_time(0.0) == pytest.approx(45.0)
    assert cost.travel_time(2000.0) == pytest.approx(45.0)


def test_linear_cost_with_congestion() -> None:
    cost = LinearCost(alpha=0.0, beta=0.01)

    assert cost.travel_time(0.0) == pytest.approx(0.0)
    assert cost.travel_time(2000.0) == pytest.approx(20.0)
    assert cost.travel_time(4000.0) == pytest.approx(40.0)


def test_linear_cost_integral() -> None:
    cost = LinearCost(alpha=45.0, beta=0.01)

    result = cost.integral(100.0)

    expected = 45.0 * 100.0 + 0.5 * 0.01 * 100.0**2

    assert result == pytest.approx(expected)


def test_linear_cost_rejects_negative_flow() -> None:
    cost = LinearCost(alpha=45.0, beta=0.01)

    with pytest.raises(ValueError):
        cost.travel_time(-1.0)


def test_bpr_cost_at_zero_flow_equals_free_flow_time() -> None:
    cost = BPRCost(
        free_flow_time=60.0,
        capacity=1000.0,
    )

    assert cost.travel_time(0.0) == pytest.approx(60.0)


def test_bpr_cost_increases_with_flow() -> None:
    cost = BPRCost(
        free_flow_time=60.0,
        capacity=1000.0,
    )

    time_at_zero = cost.travel_time(0.0)
    time_at_capacity = cost.travel_time(1000.0)
    time_above_capacity = cost.travel_time(1500.0)

    assert time_at_zero < time_at_capacity
    assert time_at_capacity < time_above_capacity


def test_bpr_rejects_non_positive_capacity() -> None:
    with pytest.raises(ValueError):
        BPRCost(
            free_flow_time=60.0,
            capacity=0.0,
        )