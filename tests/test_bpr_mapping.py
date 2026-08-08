import pytest

from braess.urban import (
    resolve_bpr_parameters,
)


@pytest.mark.parametrize(
    (
        "highway",
        "expected_type",
        "expected_alpha",
        "expected_beta",
    ),
    [
        (
            "motorway",
            "motorways",
            0.65625,
            4.8,
        ),
        (
            "motorway_link",
            "motorways",
            0.65625,
            4.8,
        ),
        (
            "primary",
            "urban_arterials",
            1.0,
            1.5,
        ),
        (
            "secondary",
            "urban_arterials",
            1.0,
            1.5,
        ),
        (
            "tertiary",
            "urban_streets",
            1.28571,
            1.0,
        ),
        (
            "residential",
            "urban_streets",
            1.28571,
            1.0,
        ),
    ],
)
def test_resolve_bpr_parameters(
    highway: str,
    expected_type: str,
    expected_alpha: float,
    expected_beta: float,
) -> None:
    (
        link_type,
        alpha,
        beta,
    ) = resolve_bpr_parameters(
        highway
    )

    assert link_type == expected_type

    assert alpha == pytest.approx(
        expected_alpha
    )

    assert beta == pytest.approx(
        expected_beta
    )


def test_unknown_highway_defaults_to_urban_street() -> None:
    (
        link_type,
        alpha,
        beta,
    ) = resolve_bpr_parameters(
        "unknown_type"
    )

    assert (
        link_type
        == "urban_streets"
    )

    assert alpha == pytest.approx(
        1.28571
    )

    assert beta == pytest.approx(
        1.0
    )