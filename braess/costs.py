from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class CostFunction(Protocol):
    """
    Interface comum para funções de tempo de viagem.

    Uma função de custo deve ser capaz de calcular:

    1. o tempo de viagem para determinado fluxo;
    2. a integral da função entre zero e o fluxo.

    A integral será utilizada na função objetivo de Beckmann e na busca
    do tamanho do passo do algoritmo de Frank-Wolfe.
    """

    def travel_time(self, flow: float) -> float:
        """
        Calcula o tempo de viagem para determinado fluxo.
        """

    def integral(self, flow: float) -> float:
        """
        Calcula a integral da função de custo entre zero e o fluxo.
        """


def _validate_flow(flow: float) -> None:
    if flow < 0:
        raise ValueError("O fluxo não pode ser negativo.")


@dataclass(frozen=True, slots=True)
class LinearCost:
    """
    Função linear de tempo de viagem.

    A função é definida por:

        t(x) = alpha + beta * x

    em que:

    - ``x`` é o fluxo da aresta;
    - ``alpha`` é o tempo independente do fluxo;
    - ``beta`` representa o efeito do congestionamento.

    Essa função será utilizada na rede sintética do paradoxo de Braess.
    """

    alpha: float
    beta: float

    def __post_init__(self) -> None:
        if self.alpha < 0:
            raise ValueError("O parâmetro alpha não pode ser negativo.")

        if self.beta < 0:
            raise ValueError("O parâmetro beta não pode ser negativo.")

    def travel_time(self, flow: float) -> float:
        """
        Calcula:

            t(x) = alpha + beta * x
        """
        _validate_flow(flow)

        return self.alpha + self.beta * flow

    def integral(self, flow: float) -> float:
        """
        Calcula:

            integral de 0 até x de t(w) dw

        Para a função linear:

            alpha * x + (beta / 2) * x²
        """
        _validate_flow(flow)

        return (
            self.alpha * flow
            + 0.5 * self.beta * flow**2
        )


@dataclass(frozen=True, slots=True)
class BPRCost:
    """
    Função de custo BPR para redes viárias urbanas.

    A função é definida por:

        t(x) = t0 * [1 + alpha * (x / capacity)^beta]

    em que:

    - ``t0`` é o tempo de viagem em fluxo livre;
    - ``x`` é o fluxo da aresta;
    - ``capacity`` é a capacidade estimada;
    - ``alpha`` e ``beta`` controlam o crescimento do congestionamento.
    """

    free_flow_time: float
    capacity: float
    alpha: float = 0.15
    beta: float = 4.0

    def __post_init__(self) -> None:
        if self.free_flow_time <= 0:
            raise ValueError(
                "O tempo de fluxo livre deve ser maior que zero."
            )

        if self.capacity <= 0:
            raise ValueError(
                "A capacidade deve ser maior que zero."
            )

        if self.alpha < 0:
            raise ValueError(
                "O parâmetro alpha da BPR não pode ser negativo."
            )

        if self.beta <= 0:
            raise ValueError(
                "O parâmetro beta da BPR deve ser maior que zero."
            )

    def travel_time(self, flow: float) -> float:
        """
        Calcula o tempo congestionado da aresta.
        """
        _validate_flow(flow)

        volume_capacity_ratio = flow / self.capacity

        return self.free_flow_time * (
            1.0
            + self.alpha
            * volume_capacity_ratio**self.beta
        )

    def integral(self, flow: float) -> float:
        """
        Calcula a integral analítica da função BPR.

        O resultado é:

            t0 * [
                x
                + alpha * x^(beta + 1)
                  / ((beta + 1) * capacity^beta)
            ]
        """
        _validate_flow(flow)

        congestion_integral = (
            self.alpha
            * flow ** (self.beta + 1)
            / (
                (self.beta + 1)
                * self.capacity**self.beta
            )
        )

        return self.free_flow_time * (
            flow + congestion_integral
        )