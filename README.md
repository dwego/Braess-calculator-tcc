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

## Experimentos configuráveis do TCC

O runner `run_tcc_experiments.py` executa mapas, rotas O-D, sentidos, demandas e
remoções definidos em JSON, sem editar o código. A configuração
[`experiments/tcc_scenarios.json`](experiments/tcc_scenarios.json) descreve os
36 cenários-base de São José dos Campos; as coordenadas devem ser preenchidas
ou resolvidas antes da preparação.

Teste o pipeline com a rede sintética incluída, sem internet:

```bash
python run_tcc_experiments.py prepare --config experiments/example_scenarios.json --output outputs/example-inputs
python run_tcc_experiments.py run --config outputs/example-inputs/scenarios.json --output outputs/example-run
```

O [guia da bateria experimental](docs/experimentos-tcc.md) explica como resolver
os pontos, congelar as redes, rodar a bateria completa com um comando e testar
outros mapas alterando apenas a configuração.
