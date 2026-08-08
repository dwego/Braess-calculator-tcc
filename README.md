# Braess Calculator TCC

English Version: [README_en.md](README_en.md)

Modelo computacional desenvolvido para um Trabalho de Conclusão de Curso do Ensino Médio do Instituto Alpha Lumen.

Autores:

- Diego Trigo Araujo
- Luis Felipe Nascimento de Freitas
- Icaro Santana Ferreira Josino

O projeto tem como objetivo estudar possíveis manifestações do Paradoxo de Braess em redes viárias urbanas por meio de modelagem em grafos, atribuição de tráfego e cálculo de equilíbrio.

A rede viária é representada como um `MultiDiGraph` e utiliza dados do OpenStreetMap por meio do OSMnx. O modelo implementa funções de custo de tráfego, atribuição All-or-Nothing, menor caminho com Dijkstra e o algoritmo de Frank-Wolfe para aproximar o equilíbrio de Wardrop.

Também são executados experimentos de remoção de conexões, permitindo recalcular o equilíbrio da rede após alterações em sua topologia.

## Documentação

Para uma explicação completa do fluxo computacional, decisões de implementação, modelos matemáticos e funcionamento do software, consulte:

[`docs/modelo-computacional.md`](docs/modelo-computacional.md)