# Bateria experimental configurável

O runner `run_tcc_experiments.py` lê mapas, pontos, direções, demandas,
capacidades, tolerâncias e seleção de arestas de um JSON. Para estudar outra
cidade ou outro recorte, crie outro JSON e passe `--config`; nenhum nome de rua,
coordenada ou par O-D está embutido no runner.

As rotas da configuração são **pares origem-destino direcionados**. Os caminhos
e os fluxos são calculados pelo solver. Cada direção e demanda constitui um
experimento independente, com um único par O-D; as demandas das diferentes
linhas não são somadas numa mesma atribuição.

## Instalação e teste sem internet

Use Python 3.11 ou superior e instale as dependências do projeto:

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

O arquivo `experiments/example_network.graphml` contém uma rede **sintética**
pequena, com arestas paralelas. Ele serve para testar o pipeline, não representa
dados OSM nem resultados do TCC. Os dois comandos abaixo preparam suas entradas
e executam duas direções com duas remoções cada, incluindo as imagens:

```bash
python run_tcc_experiments.py prepare --config experiments/example_scenarios.json --output outputs/example-inputs
python run_tcc_experiments.py run --config outputs/example-inputs/scenarios.json --output outputs/example-run
```

Os diretórios de saída devem ser novos: execuções anteriores não são sobrescritas.
Omitir `--output` cria um nome com data e hora UTC em `outputs/`.

## Preparar os três mapas do TCC

`experiments/tcc_scenarios.json` contém as oito interseções solicitadas, as
12 direções e as demandas 2000, 4000 e 6000 veíc/h: **36 cenários-base**.
As coordenadas começam como `null`, pois os endereços textuais não fornecem
uma localização verificada. Nenhum extremo oeste/leste é escolhido automaticamente.

```bash
python run_tcc_experiments.py validate --config experiments/tcc_scenarios.json
```

`validate` verifica a estrutura e informa as coordenadas pendentes sem acessar
a internet. Resolva e confira a geometria antes de iniciar a bateria:

```bash
python resolve_tcc_points.py --config experiments/tcc_scenarios.json --output-config experiments/tcc_scenarios_resolved.json
```

O resolvedor encontra as interseções na própria malha OSM, calcula o recorte,
verifica os sentidos das rotas e salva GraphML, CSV e PNGs a 300 dpi. Nominatim
serve apenas à localização da região de busca. O ponto A do mapa 2 é um
`junction_group`: suas duas junções permanecem separadas, e cada direção possui
um nó de entrada/saída explícito. As escolhas precisam de conferência visual.
O [guia de resolução geográfica](resolucao-pontos-tcc.md) descreve os critérios,
limites, imagens e como resolver outros mapas. Esta etapa não chama o solver.

O comando antigo `run_tcc_experiments.py resolve-points --config ... --output ...`
também utiliza o novo resolvedor. Após aprovar visualmente o JSON produzido:

```bash
python run_tcc_experiments.py prepare --config experiments/tcc_scenarios_resolved.json --output outputs/tcc-inputs
```

`prepare` usa o `build_graph()` existente, com `network_type="drive"` e
`simplify=True`. Cada mapa é construído uma vez e exportado em GraphML **antes**
de adicionar custos BPR ou fluxos. O comando registra:

- coordenadas fixas dos pontos e os IDs OSM retornados por `nearest_nodes`;
- coordenadas dos nós, distância de associação e CRS métrico usado;
- centro, raio, número de nós/arestas, direções e nós O-D;
- hash SHA-256 da rede, além da configuração em `scenarios.json`.

O centro padrão é a média das coordenadas do mapa e o raio é a distância
geodésica ao ponto mais distante mais `margin_m` (1000 m por padrão).
`center: {"latitude": ..., "longitude": ...}` e `radius_m` podem ser definidos
explicitamente por mapa. Um raio que exclui pontos é rejeitado. A margem é um
recorte experimental, não uma garantia de conter todos os desvios relevantes:
ajuste-a no JSON para comparar sensibilidades ao tamanho da rede.

A associação a nós usa `project_graph` e `nearest_nodes` em CRS métrico, com
SciPy, já utilizado pelo solver. Não exige instalar scikit-learn. Uma distância
maior que `max_snap_distance_m` (300 m por padrão), ou origem e destino associados
ao mesmo nó, gera um erro claro. Nenhuma componente fortemente conectada é
selecionada para substituir silenciosamente os pontos: a conectividade de cada
direção é avaliada na própria rede congelada.

## Executar a bateria completa

Depois da preparação, um comando executa todos os cenários:

```bash
python run_tcc_experiments.py run --config outputs/tcc-inputs/scenarios.json --output outputs/tcc-results
```

`run` exige entradas preparadas e **não baixa redes nem faz geocoding**.
Os hashes são verificados e os IDs fixos são conferidos contra as coordenadas.
Uma cópia portátil de todas as entradas fica em `tcc-results/inputs/`; para
repetir a bateria, use o `inputs/scenarios.json` desse diretório como configuração.
Mantenha junto dele o subdiretório `maps/`. Os caminhos relativos de GraphML
são interpretados a partir do JSON, independentemente do diretório de execução.

As funções existentes de Frank-Wolfe, BPR, All-or-Nothing e Relative Gap são
reutilizadas sem alteração de sua matemática. Cada mapa é preparado com
`prepare_urban_graph`; cada combinação direção/demanda calcula o baseline
**uma vez**, que é reaproveitado em todas as remoções. Cada remoção começa com
uma cópia independente da rede original. A exportação dos tempos modificados
atualiza a cópia com os fluxos do resultado, sem executar novamente o solver.

## Smoke test de um cenário

Use filtros sobre o JSON resolvido (ou sobre o `scenarios.json` preparado) para
executar apenas um mapa, uma direção e uma demanda:

```bash
python run_tcc_experiments.py run \
  --config experiments/tcc_scenarios_resolved.json \
  --map mapa_1 --route A_to_B --demand 2000 \
  --candidate-limit 3 --plot-level all \
  --output outputs/tcc-smoke-mapa-1
```

Esse comando executa um baseline e **no máximo três candidatas** à remoção.
A matemática, as tolerâncias do solver e a seleção existente por fluxo continuam
as mesmas. O limite também trunca listas explícitas de `removal_edges`, mantendo
a ordem configurada. Sem `--candidate-limit`, permanece o comportamento do JSON.
O limite deve ser um inteiro positivo.

`--map`, `--route` e `--demand` selecionam valores já presentes na configuração.
A demanda por rota prevalece sobre a lista global; uma demanda ausente, um ID
inexistente ou uma combinação vazia retorna erro antes de executar cenários ou
criar saídas. Sem `--map`, um ID de rota pode selecionar rotas de vários mapas.
O terminal mostra o número de cenários selecionados. Os mesmos filtros são
aceitos por `validate` para conferir a seleção sem executar o solver, e por
`prepare` para congelar somente os mapas selecionados. Não se aplicam a
`resolve-points`, que prepara a geometria separadamente.

Os filtros preservam todos os pontos do mapa, membros de grupos, centro, raio,
snapshot e `origin_node`/`destination_node` de cada rota. Para o mapa 2 resolvido,
`--map mapa_2 --route A_to_B` usa a origem A2 (`1425164988`), enquanto
`--map mapa_2 --route B_to_A` usa o destino A1 (`1425156870`). A CLI não resolve
novamente o complexo nem escolhe outro membro. Uma rota de grupo sem nó definido
é rejeitada antes da execução.

| `--plot-level` | Figuras PNG |
| --- | --- |
| `none` | Nenhuma. |
| `baseline` | Fluxos e convergência apenas do baseline. |
| `all` | Fluxos e convergência do baseline e de cada remoção com solução. |

Os CSVs e JSONs numéricos são gerados em todos os níveis. A flag sobrescreve
`images.enabled` e `images.plot_level` somente na cópia da execução; sem a flag,
o JSON controla as figuras e o nível padrão é `all`. `images.enabled: false`
desliga todas as imagens. O arquivo de entrada permanece intacto, e
`<output>/inputs/scenarios.json` registra a seleção e os parâmetros efetivamente
usados para reproduzir o smoke test. O diretório de saída deve ser novo.

### Leitura dos mapas de fluxo

`flows.png` mostra a rede completa em cinza claro, com origem e destino marcados
pelos labels da rota nos nós efetivamente utilizados. `minimum_active_flow`
controla apenas o destaque colorido; nenhuma rua do fundo é removida pelo limiar.
A espessura representa fluxo absoluto e a cor representa fluxo/capacidade,
com uma paleta azul/verde para baixa utilização, amarelo próximo de 0,8–1,0
e laranja/vermelho acima da capacidade. O fundo fino tem contraste moderado e os
marcadores O-D grandes usam labels em negrito e contorno branco.
As espessuras usam escala logarítmica suave, máximo de 2,1 pontos e um limite
adicional proporcional ao comprimento desenhado dos segmentos curtos.

O baseline e todas as remoções com solução de um mesmo cenário compartilham
o máximo de fluxo, calculado sobre o conjunto dessas soluções. A escala de cor
é fixa em V/C de 0 a 1,5 em todas as demandas e cenários, com clipping apenas
visual acima de 1,5 (extremo indicado por “1,5+”). Os valores reais continuam
nos CSVs e nas métricas. As figuras de um cenário também
compartilham o enquadramento completo e o recorte do detalhe. A exportação dos
mapas aguarda as soluções para fixar essas escalas; os cálculos e CSVs numéricos
não são modificados. `flow_plot.json` registra os limites, os nós O-D e a aresta
removida para conferir a comparação.

Nas remoções, o trecho excluído aparece em magenta tracejado usando sua geometria
original do baseline, com 2,9 pontos de largura e halo branco, acima do máximo
das linhas de fluxo. Um detalhe ampliado comum aos cenários torna visíveis
segmentos que seriam pequenos demais na visão geral. A rede original continua
no fundo, inclusive nas figuras das redes modificadas.

Cada remoção com solução também gera `delta_flow.png` quando o nível é `all`:

```text
delta = modified_flow - baseline_flow
```

Azul representa redução, vermelho representa aumento e cinza representa
valores próximos de zero. A escala divergente é
simétrica em torno de zero, comum às remoções desse cenário; a espessura representa
o módulo do delta. A removida tem fluxo modificado zero e delta igual ao negativo
do fluxo baseline. O limiar de destaque de `flows.png` não oculta redistribuições
na figura de delta; a rede completa permanece no fundo.

Arestas OSM com geometrias coincidentes são separadas por um pequeno deslocamento
apenas no desenho, mantendo cada `(u, v, key)` e suas cores/espessuras. Setas
indicam o sentido onde há espaço. Geometrias paralelas já distintas permanecem
nas posições originais. Nenhuma aresta ou fluxo é agregado numericamente.
Os PNGs são exportados a 300 dpi em layout de 12 × 8,5 polegadas, com detalhe,
escala de cores e notas explicativas na coluna lateral.

## Definir outros mapas e rotas

Copie `experiments/tcc_scenarios.json`, substitua `maps` e passe o novo caminho
em `--config`. Cada mapa possui:

| Campo | Uso |
| --- | --- |
| `id` | Identificador único, sem espaços ou barras; usado nos diretórios. |
| `locality` | Região da rede OSM usada para resolver as interseções; não é usada durante `run`. |
| `points` | Dicionário por label com interseções simples ou `type: "junction_group"` e `nodes`. |
| `routes` | Pares dirigidos com `id`, `origin`, `destination` e, para grupos, `origin_node`/`destination_node`. |
| `margin_m`, `center`, `radius_m` | Recorte da rede. Centro e raio explícitos são opcionais. |
| `max_snap_distance_m` | Distância máxima entre coordenada e nó associado. |
| `graphml` | Opcional: rede OSMnx bruta local, EPSG:4326, de automóveis e já simplificada. |
| `removal_edges` | Opcional: lista explícita de `{ "u": 123, "v": 456, "key": 0 }`. |

O sentido inverso só é executado se houver outra entrada em `routes`. Uma rota
pode definir sua própria lista `demands`; se omitida, usa a lista global. Para
experimentar mudanças nas coordenadas de entradas já preparadas, resolva e
valide novamente. Para baixar uma versão atual da mesma rede, remova `graphml`
e `graph_sha256`; `prepare` reassocia pelas coordenadas, valida o snap e atualiza
os IDs selecionados nas rotas. Manter `graphml` reutiliza a rede fornecida;
snapshots com hash exigem a preservação dos IDs.

Os demais parâmetros também ficam no JSON:

- `solver`: tolerância do Relative Gap, limite de iterações e tolerância da busca linear;
- `urban`: capacidades por faixa por classe viária, capacidade e faixas padrão;
- `removals`: `limit`, `minimum_flow`, `excluded_highway_types`, `numerical_tolerance`;
- `images`: `enabled`, `plot_level` (`none`, `baseline`, `all`) e `minimum_active_flow` (limiar **visual**, sem excluir dados do CSV).

Por padrão são testadas as dez arestas de maior fluxo acima de 40 veíc/h,
excluindo `service`, usando a seleção existente. `limit: null` seleciona todas
as arestas que passam pelos filtros. `removal_edges`, quando presente no mapa,
substitui essa seleção, permitindo reproduzir uma lista exata de candidatas.
Uma lista explícita vazia executa apenas os baselines. A remoção afeta somente
a aresta direcionada `(u, v, key)`; não remove automaticamente o sentido inverso
nem outras arestas com o mesmo nome ou OSMID.

## Resultados e unidades

```text
tcc-results/
  experiment.json              # versões, commit, parâmetros BPR, contagens e tempo total
  baselines.csv                # um registro por mapa/direção/demanda, incluindo falhas
  removals.csv                 # um registro por aresta testada
  aggregated.csv               # contagens por mapa e status
  inputs/
    scenarios.json
    maps/<map_id>/network.graphml
    maps/<map_id>/metadata.json
  scenarios/<map_id>/<route_id>/demand-<demanda>/
    summary.json
    removals.csv
    baseline/
      edges.csv
      convergence.csv
      solver.json
      flows.png
      convergence.png
      flow_plot.json
    removals/<u>_<v>_<key>/
      result.json
      edges.csv
      convergence.csv
      solver.json
      flows.png
      convergence.png
      delta_flow.png
      flow_plot.json
```

Remoções sem solução possuem `result.json`, com erro/status, sem arquivos de
um solver inexistente. As figuras são PNGs a 300 dpi. Os CSVs detalhados e o
histórico são salvos também para soluções que atingiram o limite de iterações.
Arquivos agregados são atualizados após cada cenário e o CSV local após cada
remoção. As listas OSM e os erros de exportação em tabelas agregadas usam JSON
dentro da célula CSV. Falhas de imagem ficam em `artifact_errors` e não interrompem
as próximas remoções.

Fluxos, demandas e capacidades usam veíc/h; tempos de viagem usam segundos.
TSTT é a soma de fluxo × tempo, em veíc·s/h; sua divisão pela demanda resulta
no tempo médio em segundos. Os tempos computacionais usam `perf_counter()`:

| Campo | Intervalo medido |
| --- | --- |
| `baseline_runtime_seconds` | Chamada única ao Frank-Wolfe do baseline, incluindo suas métricas finais. |
| `RemovalResult.total_runtime_seconds` / CSV `removal_runtime_seconds` | Cópia + remoção + conectividade + solver + métricas/comparação final. |
| `solver_runtime_seconds` | Somente Frank-Wolfe da remoção; zero quando ele não foi executado. |
| `scenario_runtime_seconds` | Baseline, remoções e exportações do cenário, até montar seu resumo. |
| `total_experiment_runtime_seconds` | Preparação das cópias locais, todos os cenários e agregação, até montar o relatório final. |

O download/geocoding pertence à preparação anterior à bateria. A cópia extra
feita para exportar cada solução fica fora do tempo individual da remoção.
Falhas e desconexões também têm seus tempos medidos.

O CSV de remoções inclui os campos de identificação O-D, atributos da aresta,
fluxo/tempo/V-C do baseline, convergência dos dois cenários, iterações, gaps,
objetivos de Beckmann, TSTTs, tempos médios e computacionais. Os status são:

- `OK`: baseline e solução modificada convergiram;
- `DISCONNECTED`: a rede não conecta o par O-D;
- `NO_CONVERGENCE`: ao menos uma das duas soluções não convergiu;
- `ERROR`: falha na cópia, aresta inexistente, solver ou execução do cenário.

Uma falha de baseline fica em `baselines.csv` e as próximas direções/demandas
continuam. Remoções com falha não interrompem as candidatas seguintes. Resultados
não convergidos são exportados para diagnóstico, mas nunca marcados como Braess.

```text
absolute_improvement = baseline_tstt - modified_tstt
relative_improvement = absolute_improvement / baseline_tstt
relative_improvement_percent = 100 * relative_improvement
```

`possible_braess` exige conectividade, **ambos** os resultados convergidos e
melhoria absoluta acima de `numerical_tolerance`, conforme a definição existente.
Mesmo assim é um resultado do modelo, condicionado às hipóteses de demanda,
capacidades, parâmetros BPR e recorte da rede.

O processo retorna código 2 quando há erro de configuração/execução/exportação.
Desconexões e falta de convergência são resultados científicos registrados nas
tabelas e contagens; por si só não fazem a bateria retornar erro. Não confunda
`COMPLETED` com a convergência de todos os cenários: consulte os status.

### Acompanhar testes com 2000, 4000 e 6000 veíc/h

Use a configuração resolvida completa, que contém as três demandas. Omitir
`--demand` mantém todas as demandas configuradas da rota; uma configuração
congelada de smoke test com apenas 2000 não recupera as demais demandas.

```bash
set -o pipefail
.venv/bin/python -u run_tcc_experiments.py run \
  --config experiments/tcc_scenarios_resolved.json \
  --map mapa_1 --route A_to_B \
  --candidate-limit 3 --plot-level all \
  --output outputs/tcc-mapa-1-tres-demandas \
  2>&1 | tee tcc-mapa-1-tres-demandas.log
```

Escolha um diretório de saída novo a cada execução. O comando executa três
baselines e até nove remoções. Para testar outra rota ou mapa, troque os filtros.
Use `--demand 4000`, por exemplo, para executar somente essa demanda.

Os logs são enviados imediatamente ao terminal, com horário local, cenário
atual/total, mapa, rota, demanda, nós O-D, remoção atual/total, início/fim de
cada cálculo, convergência, iterações, gap, TSTT e caminhos dos resultados.
Etapas demoradas emitem uma mensagem de atividade a cada 15 segundos; ela informa
tempo decorrido, não avanço de iterações nem uma estimativa de conclusão.
Erros do solver e da exportação aparecem nos logs. O solver e os CSVs mantêm
a lógica existente; os tempos medidos podem variar com a execução.

### Saturação e comparação entre demandas

Aresta ativa significa estritamente `flow > minimum_active_flow`. Os indicadores
não ponderam por comprimento ou fluxo: cada aresta dirigida OSM ativa conta uma
vez, preservando arestas paralelas. As médias e medianas excluem ruas inativas.

Cada baseline exporta `max_vc_ratio`, `mean_active_vc_ratio`,
`median_active_vc_ratio`, contagens `edges_vc_gt_0_8/1_0/1_5` e percentuais
`percent_active_edges_vc_gt_0_8/1_0/1_5` (0–100). As comparações são estritas
(`>`). `active_edge_count` e `minimum_active_flow` registram o denominador
e o limiar. Sem arestas ativas, contagens são zero e média, mediana, máximo e
percentuais ficam nulos; sem resultado do solver, também as contagens ficam nulas.
Capacidade inválida em aresta ativa gera erro, nunca um V/C artificialmente zero.

As métricas aparecem em `baseline/summary.json`, no `summary.json` do cenário,
em `scenario_summary.csv` (por cenário e consolidado na raiz) e em
`baselines.csv`. Cada baseline com imagens habilitadas gera
`baseline/vc_distribution.png`: histograma dos valores reais de V/C, incluindo
os superiores a 1,5, com linhas em 0,8, 1,0 e 1,5. Com duas ou mais demandas
para o mesmo mapa/O-D, o pipeline gera `scenarios/<mapa>/<rota>/vc_demand_comparison.png`.
Com `--plot-level none`, as métricas continuam sendo salvas, mas nenhum PNG é criado.

A comparação mostra máximo, média e mediana de V/C, percentuais acima de 0,8
e 1,0, status e gap de cada baseline. `NO_CONVERGENCE` significa apenas que
o critério de convergência não foi atendido; não comprova saturação. Soluções
parciais mantêm seus indicadores, identificadas como tal. Nas remoções,
`final_relative_gap`, `iterations` e `max_vc_ratio` são gravados em
`result.json` e nos CSVs de remoções quando há resultado utilizável.
O critério existente de `possible_braess` permanece intacto e exige convergência.

O comando da seção anterior executa o smoke autorizado de três demandas,
três candidatas por demanda e todas as figuras. Ao final, o terminal resume
os indicadores de cada demanda, quantos baselines convergiram e as contagens
de remoções OK, DISCONNECTED, NO_CONVERGENCE e ERROR.
