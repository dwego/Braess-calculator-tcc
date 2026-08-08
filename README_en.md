# Braess Calculator TCC

Versão em Português: [README.md](README.md)

Computational model developed for a Brazilian high school final research project at Instituto Alpha Lumen.

Authors:

- Diego Trigo Araujo
- Luis Felipe Nascimento de Freitas
- Icaro Santana Ferreira Josino

The project aims to investigate possible manifestations of the Braess Paradox in urban road networks using graph modeling, traffic assignment and equilibrium computation.

The road network is represented as a `MultiDiGraph` and uses OpenStreetMap data through OSMnx. The model implements traffic cost functions, All-or-Nothing assignment, Dijkstra shortest-path routing and the Frank-Wolfe algorithm to approximate Wardrop equilibrium.

The software also performs link-removal experiments, recalculating the network equilibrium after changes in its topology.

## Documentation

For the complete computational workflow, implementation decisions, mathematical models and software architecture, see:

[`docs/modelo-computacional.md`](docs/modelo-computacional.md)