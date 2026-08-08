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

BPR_LINK_TYPE_ATTRIBUTE = "bpr_link_type"
BPR_ALPHA_ATTRIBUTE = "bpr_alpha"
BPR_BETA_ATTRIBUTE = "bpr_beta"


BPR_PARAMETERS: dict[str, dict[str, float]] = {
    "motorways": {
        "alpha": 0.65625,
        "beta": 4.8,
    },
    "urban_arterials": {
        "alpha": 1.0,
        "beta": 1.5,
    },
    "urban_streets": {
        "alpha": 1.28571,
        "beta": 1.0,
    },
}


BPR_LINK_TYPE_BY_HIGHWAY: dict[str, str] = {
    "motorway": "motorways",
    "motorway_link": "motorways",

    "trunk": "urban_arterials",
    "trunk_link": "urban_arterials",

    "primary": "urban_arterials",
    "primary_link": "urban_arterials",

    "secondary": "urban_arterials",
    "secondary_link": "urban_arterials",

    "tertiary": "urban_streets",
    "tertiary_link": "urban_streets",

    "residential": "urban_streets",
    "living_street": "urban_streets",
    "unclassified": "urban_streets",
    "service": "urban_streets",
}


def prepare_urban_graph(
    graph: nx.MultiDiGraph,
    *,
    capacity_per_lane: Mapping[str, float],
    default_capacity_per_lane: float,
    default_lanes: int = 1,
    copy_graph: bool = True,
) -> nx.MultiDiGraph:
    """
    Prepara uma rede urbana para a atribuição de tráfego.

    Para cada aresta, a função:

    1. preserva o tempo de fluxo livre calculado anteriormente;
    2. normaliza a classificação highway do OpenStreetMap;
    3. normaliza a quantidade de faixas;
    4. estima a capacidade da aresta;
    5. converte a classificação OSM para uma categoria BPR;
    6. obtém alpha e beta da categoria correspondente;
    7. associa uma função BPR à aresta;
    8. inicializa o tempo congestionado com fluxo zero.

    Os parâmetros alpha e beta não são calibrados localmente por esta
    função. São adotados de valores calibrados reportados na literatura.

    Parameters
    ----------
    graph:
        Rede urbana representada por um MultiDiGraph. As arestas devem
        possuir o atributo ``travel_time`` antes do processamento.

    capacity_per_lane:
        Capacidade adotada por faixa de acordo com a classificação
        ``highway`` do OpenStreetMap.

    default_capacity_per_lane:
        Capacidade por faixa usada quando nenhuma regra específica existir.

    default_lanes:
        Quantidade de faixas utilizada quando o atributo ``lanes`` estiver
        ausente ou for impossível de interpretar.

    copy_graph:
        Se verdadeiro, o grafo original não é modificado.

    Returns
    -------
    nx.MultiDiGraph
        Grafo preparado com capacidade, categoria BPR, parâmetros BPR e
        funções de custo em todas as arestas.
    """
    if not isinstance(graph, nx.MultiDiGraph):
        raise TypeError(
            "A rede urbana deve ser um networkx.MultiDiGraph."
        )

    if (
        not math.isfinite(default_capacity_per_lane)
        or default_capacity_per_lane <= 0.0
    ):
        raise ValueError(
            "A capacidade padrão por faixa deve ser positiva e finita."
        )

    if default_lanes <= 0:
        raise ValueError(
            "A quantidade padrão de faixas deve ser positiva."
        )

    prepared_graph = (
        deepcopy(graph)
        if copy_graph
        else graph
    )

    for u, v, key, data in prepared_graph.edges(
        keys=True,
        data=True,
    ):
        edge_id = EdgeId(
            u=u,
            v=v,
            key=key,
        )

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

        (
            capacity_per_lane_value,
            capacity_source,
        ) = resolve_capacity_per_lane(
            highway=highway,
            capacity_per_lane=capacity_per_lane,
            default_capacity_per_lane=(
                default_capacity_per_lane
            ),
        )

        total_capacity = (
            capacity_per_lane_value
            * lanes
        )

        if not math.isfinite(total_capacity):
            raise ValueError(
                f"A capacidade da aresta {edge_id} não é finita."
            )

        if total_capacity <= 0.0:
            raise ValueError(
                f"A capacidade da aresta {edge_id} deve ser positiva."
            )

        (
            bpr_link_type,
            bpr_alpha,
            bpr_beta,
        ) = resolve_bpr_parameters(
            highway
        )

        cost_function = BPRCost(
            free_flow_time=free_flow_time,
            capacity=total_capacity,
            alpha=bpr_alpha,
            beta=bpr_beta,
        )

        data[
            FREE_FLOW_TIME_ATTRIBUTE
        ] = free_flow_time

        data[
            HIGHWAY_NORMALIZED_ATTRIBUTE
        ] = highway

        data[
            LANES_NORMALIZED_ATTRIBUTE
        ] = lanes

        data[
            CAPACITY_ATTRIBUTE
        ] = total_capacity

        data[
            CAPACITY_SOURCE_ATTRIBUTE
        ] = capacity_source

        data[
            BPR_LINK_TYPE_ATTRIBUTE
        ] = bpr_link_type

        data[
            BPR_ALPHA_ATTRIBUTE
        ] = bpr_alpha

        data[
            BPR_BETA_ATTRIBUTE
        ] = bpr_beta

        data[
            COST_FUNCTION_ATTRIBUTE
        ] = cost_function

        data[
            TRAVEL_TIME_ATTRIBUTE
        ] = cost_function.travel_time(
            0.0
        )

    return prepared_graph


def resolve_bpr_parameters(
    highway: str,
) -> tuple[str, float, float]:
    """
    Converte uma classificação ``highway`` do OpenStreetMap para uma
    categoria da função BPR e retorna seus parâmetros.

    Categorias adotadas:

    - motorways;
    - urban_arterials;
    - urban_streets.

    Quando uma classificação não estiver explicitamente mapeada, ela é
    tratada como ``urban_streets`` de forma conservadora.

    Returns
    -------
    tuple[str, float, float]
        Categoria BPR, alpha e beta.
    """
    link_type = (
        BPR_LINK_TYPE_BY_HIGHWAY.get(
            highway,
            "urban_streets",
        )
    )

    parameters = BPR_PARAMETERS.get(
        link_type
    )

    if parameters is None:
        raise ValueError(
            f"Categoria BPR desconhecida: {link_type!r}."
        )

    alpha = float(
        parameters["alpha"]
    )

    beta = float(
        parameters["beta"]
    )

    if alpha < 0.0:
        raise ValueError(
            "O parâmetro alpha da BPR não pode ser negativo."
        )

    if beta <= 0.0:
        raise ValueError(
            "O parâmetro beta da BPR deve ser positivo."
        )

    return (
        link_type,
        alpha,
        beta,
    )


def normalize_highway(
    value: Any,
) -> str:
    """
    Normaliza o atributo ``highway`` do OpenStreetMap.

    O atributo pode aparecer como string ou como uma coleção de valores.
    Quando houver múltiplas classificações, a primeira string válida é
    utilizada.
    """
    if isinstance(value, str):
        normalized = (
            value.strip().lower()
        )

        if normalized:
            return normalized

    if isinstance(
        value,
        list | tuple,
    ):
        for item in value:
            if (
                isinstance(item, str)
                and item.strip()
            ):
                return (
                    item
                    .strip()
                    .lower()
                )

    raise ValueError(
        f"Classificação highway inválida: {value!r}."
    )


def normalize_lanes(
    value: Any,
    *,
    default: int,
) -> int:
    """
    Normaliza o número de faixas de uma aresta.

    Exemplos de valores possíveis:

    - 2
    - "2"
    - "2;3"
    - ["1", "2"]
    - None

    Quando existirem múltiplos valores válidos, o maior é utilizado.
    """
    if default <= 0:
        raise ValueError(
            "O valor padrão de faixas deve ser positivo."
        )

    candidates = (
        _extract_lane_candidates(
            value
        )
    )

    positive_candidates = [
        candidate
        for candidate in candidates
        if candidate > 0
    ]

    if not positive_candidates:
        return default

    return max(
        positive_candidates
    )


def resolve_capacity_per_lane(
    *,
    highway: str,
    capacity_per_lane: Mapping[str, float],
    default_capacity_per_lane: float,
) -> tuple[float, str]:
    """
    Obtém a capacidade por faixa de acordo com a classe da via.

    Returns
    -------
    tuple[float, str]
        Capacidade por faixa e descrição da origem desse valor.
    """
    configured_value = (
        capacity_per_lane.get(
            highway
        )
    )

    if configured_value is not None:
        value = float(
            configured_value
        )

        if (
            not math.isfinite(value)
            or value <= 0.0
        ):
            raise ValueError(
                f"A capacidade configurada para {highway!r} "
                "deve ser positiva e finita."
            )

        return (
            value,
            f"highway:{highway}",
        )

    if (
        not math.isfinite(
            default_capacity_per_lane
        )
        or default_capacity_per_lane
        <= 0.0
    ):
        raise ValueError(
            "A capacidade padrão por faixa deve ser "
            "positiva e finita."
        )

    return (
        float(
            default_capacity_per_lane
        ),
        "default",
    )


def create_urban_zero_flows(
    graph: nx.MultiDiGraph,
) -> EdgeFlowMap:
    """
    Cria um vetor de fluxo zero para todas as arestas urbanas.
    """
    return {
        EdgeId(
            u=u,
            v=v,
            key=key,
        ): 0.0
        for u, v, key
        in graph.edges(keys=True)
    }


def _extract_lane_candidates(
    value: Any,
) -> list[int]:
    """
    Extrai possíveis valores inteiros de número de faixas.
    """
    if value is None:
        return []

    if isinstance(value, bool):
        return []

    if isinstance(value, int):
        return [value]

    if isinstance(value, float):
        if value.is_integer():
            return [
                int(value)
            ]

        return []

    if isinstance(value, str):
        normalized = (
            value
            .replace("|", ";")
            .replace(",", ";")
        )

        candidates: list[int] = []

        for part in normalized.split(";"):
            part = part.strip()

            try:
                numeric_value = float(
                    part
                )
            except ValueError:
                continue

            if numeric_value.is_integer():
                candidates.append(
                    int(numeric_value)
                )

        return candidates

    if isinstance(
        value,
        list | tuple,
    ):
        candidates: list[int] = []

        for item in value:
            candidates.extend(
                _extract_lane_candidates(
                    item
                )
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
    Converte um atributo numérico para float e exige valor positivo.
    """
    if isinstance(value, bool):
        raise ValueError(
            f"O atributo {attribute!r} da aresta {edge} "
            "não pode ser booleano."
        )

    if not isinstance(
        value,
        int | float,
    ):
        raise ValueError(
            f"A aresta {edge} não possui valor numérico "
            f"para {attribute!r}."
        )

    numeric_value = float(
        value
    )

    if not math.isfinite(
        numeric_value
    ):
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