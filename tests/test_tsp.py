import itertools
import random

import pytest

from app.services.tsp import EXACT_MAX_POINTS, loop_cost, shortest_loop


def random_costs(n_stops: int, seed: int) -> list[list[float]]:
    """Asymmetric costs between the hotel (0) and n_stops stops."""
    rng = random.Random(seed)
    size = n_stops + 1
    return [[0.0 if i == j else rng.uniform(1, 60) for j in range(size)] for i in range(size)]


def brute_force(cost: list[list[float]]) -> float:
    return min(loop_cost(cost, order) for order in itertools.permutations(range(1, len(cost))))


@pytest.mark.parametrize("n_stops", range(0, 8))
def test_exact_solver_matches_brute_force(n_stops: int) -> None:
    for seed in range(5):
        cost = random_costs(n_stops, seed)
        order = shortest_loop(cost)
        assert sorted(order) == list(range(1, n_stops + 1))
        assert loop_cost(cost, order) == pytest.approx(brute_force(cost))


def test_direction_matters_when_costs_are_asymmetric() -> None:
    # Going 0 -> 1 -> 2 -> 0 is cheap; the reverse loop is expensive.
    cost = [
        [0, 1, 50],
        [50, 0, 1],
        [1, 50, 0],
    ]
    assert shortest_loop(cost) == [1, 2]


def test_large_days_use_the_heuristic_and_visit_every_stop_once() -> None:
    n_stops = EXACT_MAX_POINTS + 5
    cost = random_costs(n_stops, seed=42)
    order = shortest_loop(cost)
    assert sorted(order) == list(range(1, n_stops + 1))
    # 2-opt never ends up worse than the nearest-neighbour tour it starts from.
    remaining, current, nearest = set(range(1, n_stops + 1)), 0, []
    while remaining:
        current = min(remaining, key=lambda k: cost[current][k])
        nearest.append(current)
        remaining.remove(current)
    assert loop_cost(cost, order) <= loop_cost(cost, nearest)


def test_points_on_a_line_are_visited_in_order() -> None:
    # Stops at 1..5 km east of the hotel: out along the line and straight back.
    positions = [0, 3, 1, 5, 2, 4]
    cost = [[abs(a - b) for b in positions] for a in positions]
    # Many orders tie (e.g. 1, 3, 5, 4, 2); every best loop just goes out to 5 km and back.
    assert loop_cost(cost, shortest_loop(cost)) == 10
