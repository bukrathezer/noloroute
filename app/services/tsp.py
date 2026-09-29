"""Shortest round trip (travelling salesman) over a small cost matrix.

Used for transit days, where Google can't choose the visiting order. Point 0 is the hotel; the
trip leaves it, visits every other point once and comes back. Costs may be asymmetric (a bus
can be quicker one way than the other), so cost[a][b] and cost[b][a] are treated separately.

- Up to EXACT_MAX_POINTS stops: Held-Karp dynamic programming, which finds the true optimum in
  O(2^n * n^2) steps: about 100,000 for 10 stops, instead of 10! = 3.6 million orders.
- Beyond that: nearest neighbour, improved with 2-opt (reverse a stretch while that helps).
"""

import math
from collections.abc import Sequence

EXACT_MAX_POINTS = 10

CostMatrix = Sequence[Sequence[float]]


def shortest_loop(cost: CostMatrix) -> list[int]:
    """The stops 1..n in the visiting order that makes 0 -> ... -> 0 cheapest."""
    n = len(cost) - 1
    if n <= 2:
        # One stop has one order; with two, compare both directions.
        order = list(range(1, n + 1))
        return order if n < 2 or loop_cost(cost, order) <= loop_cost(cost, order[::-1]) else order[::-1]
    if n <= EXACT_MAX_POINTS:
        return _held_karp(cost)
    return _two_opt(cost, _nearest_neighbour(cost))


def loop_cost(cost: CostMatrix, order: Sequence[int]) -> float:
    path = [0, *order, 0]
    return sum(cost[a][b] for a, b in zip(path, path[1:], strict=False))


def _held_karp(cost: CostMatrix) -> list[int]:
    n = len(cost) - 1
    # Stop k (1..n) is bit k-1 of a mask. best[mask][k]: the cheapest way to leave the hotel,
    # visit exactly the stops in `mask` and end at stop k. Every path to a bigger set extends
    # a best path to a smaller one, so each set is solved once, smallest sets first.
    best = [[math.inf] * (n + 1) for _ in range(1 << n)]
    came_from = [[0] * (n + 1) for _ in range(1 << n)]
    for k in range(1, n + 1):
        best[1 << (k - 1)][k] = cost[0][k]

    for mask in range(1, 1 << n):
        for last in range(1, n + 1):
            so_far = best[mask][last]
            if so_far == math.inf:  # `last` not in the set, or not reachable
                continue
            for nxt in range(1, n + 1):
                bit = 1 << (nxt - 1)
                if mask & bit:
                    continue
                candidate = so_far + cost[last][nxt]
                if candidate < best[mask | bit][nxt]:
                    best[mask | bit][nxt] = candidate
                    came_from[mask | bit][nxt] = last

    # Close the loop back to the hotel, then walk the choices backwards.
    full = (1 << n) - 1
    last = min(range(1, n + 1), key=lambda k: best[full][k] + cost[k][0])
    order: list[int] = []
    mask = full
    while last:
        order.append(last)
        mask, last = mask & ~(1 << (last - 1)), came_from[mask][last]
    return order[::-1]


def _nearest_neighbour(cost: CostMatrix) -> list[int]:
    remaining = set(range(1, len(cost)))
    order: list[int] = []
    current = 0
    while remaining:
        current = min(remaining, key=lambda k: cost[current][k])
        order.append(current)
        remaining.remove(current)
    return order


def _two_opt(cost: CostMatrix, order: list[int]) -> list[int]:
    best = loop_cost(cost, order)
    improved = True
    while improved:
        improved = False
        for i in range(len(order) - 1):
            for j in range(i + 1, len(order)):
                candidate = order[:i] + order[i : j + 1][::-1] + order[j + 1 :]
                candidate_cost = loop_cost(cost, candidate)
                if candidate_cost < best - 1e-9:
                    order, best, improved = candidate, candidate_cost, True
    return order
