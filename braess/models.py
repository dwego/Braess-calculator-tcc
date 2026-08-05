from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, TypeAlias


NodeId: TypeAlias = Hashable


@dataclass(frozen=True, slots=True)
class EdgeId:
    """
    Identifica unicamente uma aresta de um MultiDiGraph.

    Em um MultiDiGraph, duas arestas podem possuir os mesmos nós de origem
    e destino. A chave ``key`` permite distinguir essas arestas paralelas.

    Attributes
    ----------
    u:
        Nó de origem da aresta.
    v:
        Nó de destino da aresta.
    key:
        Chave que distingue arestas paralelas.
    """

    u: NodeId
    v: NodeId
    key: Hashable


@dataclass(frozen=True, slots=True)
class ODPair:
    """
    Representa uma demanda entre uma origem e um destino.

    Attributes
    ----------
    origin:
        Nó de origem.
    destination:
        Nó de destino.
    demand:
        Quantidade de veículos que deve ser atribuída entre os dois nós.
    """

    origin: NodeId
    destination: NodeId
    demand: float

    def __post_init__(self) -> None:
        if self.origin == self.destination:
            raise ValueError(
                "A origem e o destino de um par OD devem ser diferentes."
            )

        if self.demand <= 0:
            raise ValueError(
                "A demanda de um par OD deve ser maior que zero."
            )


EdgeFlowMap: TypeAlias = dict[EdgeId, float]
EdgeCostMap: TypeAlias = dict[EdgeId, float]