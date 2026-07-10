"""HiGHS 替代官方 Gurobi fractional LP 的非官方实验实现。"""

from __future__ import annotations

import itertools
import math
import typing

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix


class HighsFractionalGridSolver:
    """只替代官方 FractionalGridSolver 的 LP 求解器，后续流程仍使用官方对象。"""

    def __init__(self, *, positive_threshold: float = 0.01):
        self.positive_threshold = float(positive_threshold)
        self.last_result: typing.Any = None
        self.last_variable_count = 0
        self.last_constraint_count = 0

    def description(self) -> str:
        return "HighsFractionalGridSolver: non-official scipy.optimize.linprog replacement for Gurobi LP."

    def __call__(self, instance):
        from pcpptc.grid_solver.grid_instance import VertexPassage
        from pcpptc.grid_solver.grid_solution import FractionalSolution

        passage_vars: list[VertexPassage] = []
        passage_index: dict[VertexPassage, int] = {}
        objective: list[float] = []

        for vertex in instance.graph.nodes:
            for first, second in itertools.combinations_with_replacement(instance.graph.neighbors(vertex), r=2):
                passage = VertexPassage(vertex, end_a=first, end_b=second)
                passage_index[passage] = len(objective)
                passage_vars.append(passage)
                objective.append(float(instance.touring_costs.vertex_passage_cost(passage, halving=True)))

        penalty_variables: dict[object, list[tuple[int, float]]] = {}
        for vertex in instance.graph.nodes:
            coverage_necessity = instance.coverage_necessities[vertex]
            if _no_penalty_variables_necessary(coverage_necessity):
                continue
            cheapest_cycle_cost = _compute_cost_of_cheapest_cycle(instance, vertex)
            for penalty in coverage_necessity.penalty_vector:
                if penalty < cheapest_cycle_cost:
                    penalty_variables.setdefault(vertex, []).append((len(objective), float(penalty)))
                    objective.append(float(penalty))

        variable_count = len(objective)
        bounds: list[tuple[float, float | None]] = [(0.0, None)] * variable_count
        for items in penalty_variables.values():
            for variable_index, _penalty in items:
                bounds[variable_index] = (0.0, 1.0)

        coverage_rows: list[tuple[object, int]] = []
        for vertex in instance.graph.nodes:
            coverage_necessity = instance.coverage_necessities[vertex]
            required_count = len(coverage_necessity)
            if required_count > 0:
                coverage_rows.append((vertex, required_count))

        a_ub = lil_matrix((len(coverage_rows), variable_count), dtype=float)
        b_ub = np.zeros(len(coverage_rows), dtype=float)
        for row_index, (vertex, required_count) in enumerate(coverage_rows):
            for passage, variable_index in _variables_of_vertex(instance, passage_index, vertex).items():
                a_ub[row_index, variable_index] = -1.0
            for variable_index, _penalty in penalty_variables.get(vertex, []):
                a_ub[row_index, variable_index] = -1.0
            b_ub[row_index] = -float(required_count)

        edges = list(instance.graph.edges)
        a_eq = lil_matrix((len(edges), variable_count), dtype=float)
        b_eq = np.zeros(len(edges), dtype=float)
        for row_index, edge in enumerate(edges):
            left, right = edge
            for passage, variable_index in _outgoing_variables(instance, passage_index, left, right).items():
                a_eq[row_index, variable_index] += 2.0 if passage.is_uturn() else 1.0
            for passage, variable_index in _outgoing_variables(instance, passage_index, right, left).items():
                a_eq[row_index, variable_index] -= 2.0 if passage.is_uturn() else 1.0

        result = linprog(
            c=np.asarray(objective, dtype=float),
            A_ub=a_ub.tocsr() if coverage_rows else None,
            b_ub=b_ub if coverage_rows else None,
            A_eq=a_eq.tocsr() if edges else None,
            b_eq=b_eq if edges else None,
            bounds=bounds,
            method="highs",
        )
        self.last_result = result
        self.last_variable_count = variable_count
        self.last_constraint_count = len(coverage_rows) + len(edges)
        if not result.success:
            raise RuntimeError(f"HiGHS fractional LP failed: status={result.status}, message={result.message}")

        solution = FractionalSolution()
        values = np.asarray(result.x, dtype=float)
        for passage, variable_index in passage_index.items():
            value = float(values[variable_index])
            if value > self.positive_threshold:
                solution[passage] = value
        return solution, float(result.fun)


def _no_penalty_variables_necessary(coverage_necessity) -> bool:
    if len(coverage_necessity) == 0:
        return True
    return all(value == math.inf for value in coverage_necessity.penalty_vector)


def _compute_cost_of_cheapest_cycle(instance, vertex) -> float:
    neighbor = min(
        instance.graph.neighbors(vertex),
        key=lambda item: instance.touring_costs.distance_cost_of_edge(vertex, item),
    )
    return (
        instance.touring_costs.turn_cost_at_vertex(vertex, (neighbor, neighbor))
        + 2 * instance.touring_costs.distance_cost_of_edge(vertex, neighbor)
        + instance.touring_costs.turn_cost_at_vertex(neighbor, (vertex, vertex))
    )


def _variables_of_vertex(instance, passage_index: dict, vertex) -> dict:
    from pcpptc.grid_solver.grid_instance import VertexPassage

    result = {}
    for first, second in itertools.combinations_with_replacement(instance.graph.neighbors(vertex), r=2):
        passage = VertexPassage(vertex, end_a=first, end_b=second)
        result[passage] = passage_index[passage]
    return result


def _outgoing_variables(instance, passage_index: dict, vertex, outgoing) -> dict:
    from pcpptc.grid_solver.grid_instance import VertexPassage

    result = {}
    for neighbor in instance.graph.neighbors(vertex):
        passage = VertexPassage(vertex, end_a=outgoing, end_b=neighbor)
        result[passage] = passage_index[passage]
    return result
