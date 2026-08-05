from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import networkx as nx

from braess.costs import BPRCost
from braess.models import EdgeFlowMap, EdgeId
from braess.synthetic import (
    COST_FUNCTION_ATTRIBUTE,
    TRAVEL_TIME_ATTRIBUTE,
)


FREE_FLOW_TIME_ATTRIBUTE = "free_flow_time"
CAPACITY_ATTRIBUTE = "capacity"
CAPACITY_SOURCE_ATTRIBUTE = "capacity_source"
LANES_NORMALIZED_ATTRIBUTE = "lanes_normalized"
HIGHWAY_NORMALIZED_ATTRIBUTE = "highway_normalized"


def prepare_urban_graph(
    graph: nx.MultiDiGraph,
    *,
    capacity_per_lane: Mapping[str, float],
    default_capacity_per_lane: float,
    default_lanes: int = 1,
    bpr_alpha: float = 0.15,
    bpr_beta: float = 4.0,
    copy_graph: bool = True,
) -> nx.MultiDiGraph:
    """
    Prepara uma rede urbana para a atribuição de tráfego.

    Para cada aresta, esta função:

    1. valida o tempo de fluxo livre;
    2. normaliza a classificação ``highway``;
    3. normaliza a quantidade de faixas;
    4. estima a capacidade da aresta;
    5. cria uma função de custo BPR;
    6. inicializa o tempo congestionado com fluxo zero.

    Parameters
    ----------
    graph:
        Rede urbana representada como ``MultiDiGraph``. Espera-se que
        suas arestas já possuam o atributo ``travel_time`` calculado
        pelo OSMnx.
    capacity_per_lane:
        Capacidade por faixa para cada classificação ``highway``.
        A unidade esperada é veículos por hora por faixa.
    default_capacity_per_lane:
        Capacidade por faixa utilizada quando a classificação da via
        não estiver presente nas regras fornecidas.
    default_lanes:
        Quantidade de faixas adotada quando o atributo ``lanes`` estiver
        ausente ou não puder ser interpretado.
    bpr_alpha:
        Parâmetro alpha da função BPR.
    bpr_beta:
        Expoente beta da função BPR.
    copy_graph:
        Quando verdadeiro, prepara uma cópia e preserva o grafo original.

    Returns
    -------
    nx.MultiDiGraph
        Grafo preparado para uso no solver de Frank-Wolfe.

    Raises
    ------
    TypeError
        Caso o objeto recebido não seja um ``MultiDiGraph``.
    ValueError
        Caso algum parâmetro ou atributo obrigatório seja inválido.
    """
    if not isinstance(graph, nx.MultiDiGraph):
        raise TypeError(
            "A rede urbana deve ser um networkx.MultiDiGraph."
        )

    if default_capacity_per_lane <= 0.0:
        raise ValueError(
            "A capacidade padrão por faixa deve ser positiva."
        )

    if default_lanes <= 0:
        raise ValueError(
            "A quantidade padrão de faixas deve ser positiva."
        )

    prepared_graph = deepcopy(graph) if copy_graph else graph

    for u, v, key, data in prepared_graph.edges(
        keys=True,
        data=True,
    ):
        edge_id = EdgeId(u=u, v=v, key=key)

        free_flow_time = _extract_positive_number(
            data.get(TRAVEL_TIME_ATTRIBUTE),
            attribute=TRAVEL_TIME_ATTRIBUTE,
            edge=edge_id,
        )

        highway = normalize_highway(
            data.get("highway")
        )

        lanes = normalize_lanes(
            data.get("lanes"),
            default=default_lanes,
        )

        capacity_per_lane_value, capacity_source = (
            resolve_capacity_per_lane(
                highway=highway,
                capacity_per_lane=capacity_per_lane,
                default_capacity_per_lane=(
                    default_capacity_per_lane
                ),
            )
        )

        total_capacity = (
            capacity_per_lane_value * lanes
        )

        if not math.isfinite(total_capacity):
            raise ValueError(
                f"A capacidade da aresta {edge_id} não é finita."
            )

        if total_capacity <= 0.0:
            raise ValueError(
                f"A capacidade da aresta {edge_id} "
                "deve ser positiva."
            )

        cost_function = BPRCost(
            free_flow_time=free_flow_time,
            capacity=total_capacity,
            alpha=bpr_alpha,
            beta=bpr_beta,
        )

        data[FREE_FLOW_TIME_ATTRIBUTE] = free_flow_time
        data[HIGHWAY_NORMALIZED_ATTRIBUTE] = highway
        data[LANES_NORMALIZED_ATTRIBUTE] = lanes

        data[CAPACITY_ATTRIBUTE] = total_capacity
        data[CAPACITY_SOURCE_ATTRIBUTE] = capacity_source

        data[COST_FUNCTION_ATTRIBUTE] = cost_function

        # Com fluxo igual a zero, a BPR retorna exatamente o
        # tempo de fluxo livre.
        data[TRAVEL_TIME_ATTRIBUTE] = (
            cost_function.travel_time(0.0)
        )

    return prepared_graph


def normalize_highway(value: Any) -> str:
    """
    Normaliza o atributo ``highway`` do OpenStreetMap.

    O OSMnx pode retornar uma string ou uma lista de classificações.
    Quando houver mais de uma classificação, a primeira será adotada.

    Parameters
    ----------
    value:
        Valor bruto do atributo ``highway``.

    Returns
    -------
    str
        Classificação normalizada em letras minúsculas.

    Raises
    ------
    ValueError
        Caso nenhuma classificação utilizável seja encontrada.
    """
    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized:
            return normalized

    if isinstance(value, list | tuple):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip().lower()

    raise ValueError(
        f"Classificação highway inválida: {value!r}."
    )


def normalize_lanes(
    value: Any,
    *,
    default: int,
) -> int:
    """
    Normaliza a quantidade de faixas de uma aresta.

    Valores comuns encontrados nos dados incluem:

    - ``2``;
    - ``"2"``;
    - ``"2;3"``;
    - listas como ``["2", "3"]``;
    - ausência do atributo.

    Quando houver múltiplos valores, utiliza-se o maior número inteiro
    positivo encontrado.

    Parameters
    ----------
    value:
        Valor bruto do atributo ``lanes``.
    default:
        Quantidade usada quando nenhum valor válido for encontrado.

    Returns
    -------
    int
        Quantidade de faixas normalizada.
    """
    if default <= 0:
        raise ValueError(
            "O valor padrão de faixas deve ser positivo."
        )

    candidates = _extract_lane_candidates(value)

    positive_candidates = [
        candidate
        for candidate in candidates
        if candidate > 0
    ]

    if not positive_candidates:
        return default

    return max(positive_candidates)


def resolve_capacity_per_lane(
    *,
    highway: str,
    capacity_per_lane: Mapping[str, float],
    default_capacity_per_lane: float,
) -> tuple[float, str]:
    """
    Resolve a capacidade por faixa para uma classe viária.

    Returns
    -------
    tuple[float, str]
        Capacidade por faixa e descrição da origem da regra.
    """
    configured_value = capacity_per_lane.get(highway)

    if configured_value is not None:
        value = float(configured_value)

        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(
                f"A capacidade configurada para {highway!r} "
                "deve ser positiva e finita."
            )

        return value, f"highway:{highway}"

    if (
        not math.isfinite(default_capacity_per_lane)
        or default_capacity_per_lane <= 0.0
    ):
        raise ValueError(
            "A capacidade padrão por faixa deve ser "
            "positiva e finita."
        )

    return (
        float(default_capacity_per_lane),
        "default",
    )


def create_urban_zero_flows(
    graph: nx.MultiDiGraph,
) -> EdgeFlowMap:
    """
    Cria o vetor inicial de fluxo para uma rede urbana.
    """
    return {
        EdgeId(u=u, v=v, key=key): 0.0
        for u, v, key in graph.edges(keys=True)
    }


def _extract_lane_candidates(value: Any) -> list[int]:
    """
    Extrai possíveis números de faixas de um valor bruto.
    """
    if value is None:
        return []

    if isinstance(value, bool):
        return []

    if isinstance(value, int):
        return [value]

    if isinstance(value, float):
        if value.is_integer():
            return [int(value)]

        return []

    if isinstance(value, str):
        normalized = (
            value.replace("|", ";")
            .replace(",", ";")
        )

        candidates: list[int] = []

        for part in normalized.split(";"):
            part = part.strip()

            try:
                numeric_value = float(part)
            except ValueError:
                continue

            if numeric_value.is_integer():
                candidates.append(
                    int(numeric_value)
                )

        return candidates

    if isinstance(value, list | tuple):
        candidates: list[int] = []

        for item in value:
            candidates.extend(
                _extract_lane_candidates(item)
            )

        return candidates

    return []


def _extract_positive_number(
    value: Any,
    *,
    attribute: str,
    edge: EdgeId,
) -> float:
    """
    Converte e valida um atributo numérico positivo.
    """
    if isinstance(value, bool):
        raise ValueError(
            f"O atributo {attribute!r} da aresta {edge} "
            "não pode ser booleano."
        )

    if not isinstance(value, int | float):
        raise ValueError(
            f"A aresta {edge} não possui um valor numérico "
            f"para {attribute!r}."
        )

    numeric_value = float(value)

    if not math.isfinite(numeric_value):
        raise ValueError(
            f"O atributo {attribute!r} da aresta {edge} "
            "não é finito."
        )

    if numeric_value <= 0.0:
        raise ValueError(
            f"O atributo {attribute!r} da aresta {edge} "
            "deve ser positivo."
        )

    return numeric_value