# Resolução e validação geográfica dos pontos

`resolve_tcc_points.py` prepara a geometria dos experimentos declarados no JSON.
Ele não atribui fluxos, não calcula equilíbrio e não testa remoções. A matemática
de BPR, Frank-Wolfe, Relative Gap e TSTT permanece nos módulos existentes.

## Executar e revisar

Com as dependências de `requirements.txt` instaladas, execute na raiz do projeto:

```bash
python resolve_tcc_points.py \
  --config experiments/tcc_scenarios.json \
  --output-config experiments/tcc_scenarios_resolved.json
```

O JSON original é preservado. A saída padrão das figuras é
`outputs/tcc-point-resolution/`. O resolvedor recusa um JSON de saída existente
ou um diretório de imagens não vazio. Para uma nova tentativa, escolha ambos:

```bash
python resolve_tcc_points.py \
  --config experiments/tcc_scenarios.json \
  --output-config experiments/tcc_revision_resolved.json \
  --output-dir outputs/tcc-point-resolution-revision
```

`--in-place` substitui explicitamente o JSON de entrada e cria antes uma cópia
`arquivo.json.<data-UTC>.bak`; também requer um diretório de imagens novo.
Sem `--output-config`, o nome padrão acrescenta `_resolved` ao nome da entrada.
Os artefatos gerados não são versionados automaticamente. Guarde o JSON junto
dos GraphML referenciados nele para reproduzir a rede exata.

Saídas:

| Arquivo | Conteúdo |
| --- | --- |
| `mapa_1_points.png`, `mapa_2_points.png`, `mapa_3_points.png` | Rede final inteira e pontos conceituais, em 300 dpi. |
| `<mapa>_<ponto>.png` | Zoom de cada ponto, nomes das vias e IDs dos nós. |
| `mapa_2_A.png` | As duas junções de A, setas das arestas e propostas por sentido. |
| `<mapa>.graphml` | Rede dirigida, simplificada e sem custos/fluxos experimentais. |
| `resolved_points.csv` | Coordenadas, nó, erro de resolução, snap, método e status. |
| `resolution_summary.json` | Situação de cada mapa, pontos, imagens e erros. |
| JSON resolvido | Pontos, membros, rotas, centro, raio, tentativas e hashes SHA-256. |

O CSV contém uma linha por nó físico. `point_label=A` e `member_label=A1/A2`
identificam os dois membros do mesmo ponto conceitual. O retorno do processo é
zero somente quando todos os mapas estão resolvidos e as exportações terminaram;
pendências ou erros retornam 2, mantendo os relatórios disponíveis para revisão.

## Referências visuais ativas

`experiments/tcc_scenarios.json` define quais mapas, pontos e rotas estão ativos.
As imagens de 09/09/2026 ajudam a conferir a intenção geográfica:

| Referência | Configuração |
| --- | --- |
| Desenho 11.03.19, Jardim Satélite / Bosque dos Eucaliptos / Shopping Jardim Oriente | `mapa_1`; imagem 11.02.38 sem marcações. |
| Desenho 11.06.14, região do ITA até o centro de São José dos Campos | `mapa_2`; imagem 11.04.46 sem marcações. |
| Detalhe Mário Covas × Tamoios | Zoom do ponto A de `mapa_2`, sem criar outro mapa. |
| Desenho horizontal 11.09.52, Vila Industrial / Vila Tatuetuba / Jardim Diamante | `mapa_3`; imagem 11.08.31 sem marcações. |

O desenho antigo de Vila Ema / Jardim Aquarius / Vale Sul Shopping está excluído.
Vermelho representa os corredores pretendidos; verde representa conexões físicas,
sem criar automaticamente novos pontos O-D. A/B/C/D continuam definidos no JSON.

Os desenhos não são digitalizados como restrições de caminho nesta etapa. O grafo
contém a rede `drive` do recorte calculado a partir dos pontos e de `margin_m`.
A conectividade confirma a existência de caminhos nesse recorte, mas não garante
que o desenho inteiro ou todos os desvios possíveis estejam contidos nele.
Confira o recorte nas imagens antes de adotá-lo como configuração definitiva.

## Como os nós são resolvidos

1. Baixa a rede municipal `drive`, com `simplify=True` e `retain_all=True`.
   Se a consulta municipal falhar, localiza somente a cidade e usa um recorte
   de 15 km. O cache do OSMnx e um GraphML com hash evitam repetir downloads.
2. Separa `intersection` em duas ruas, normaliza acentos, pontuação, espaços e
   abreviações (`Av.`, `R.`, `Rod.`, `Pres.`, `Mal.`, `Dr.`, entre outras).
   Os nomes originais no JSON permanecem intactos.
3. Compara `name` e `ref`, inclusive listas e valores separados por ponto e vírgula.
   Nomes principais têm precedência sobre `alt_name`, `official_name` e `short_name`
   para evitar que um nome histórico compartilhado confunda duas vias diferentes.
4. Busca nós comuns entre arestas distintas das duas ruas. Nomes agregados numa
   única aresta simplificada não bastam para confirmar um cruzamento.
5. Se necessário, compara geometrias em CRS métrico. Aceita erro de até 100 m,
   exigindo ligação topológica local de até três vezes esse limite. Isso rejeita
   cruzamentos geométricos de vias desconectadas, como viadutos sem acesso local.
6. Candidatos com erro semelhante e separados por no máximo 100 m formam um
   conjunto local; a escolha prioriza erro, centralidade geométrica, grau e ID.
   Candidatos distantes mantêm `AMBIGUOUS`, sem coordenadas inventadas.

O terminal lista candidatos, coordenadas e erros. Um `preferred_node_id` opcional
seleciona explicitamente um candidato de um ponto simples, desde que confirmado
pela busca. Para complexos viários, use um grupo em vez desse campo.

Aliases opcionais pertencem ao ponto, por exemplo:

```json
{
  "label": "A",
  "intersection": "Av. Mario Covas x Rod. dos Tamoios",
  "street_1_aliases": ["Avenida Mario Covas"],
  "street_2_aliases": ["Rodovia dos Tamoios", "SP-099"]
}
```

Para outra cidade, altere `locality`, `points` e `routes` em outro JSON e passe
`--config`. Nenhuma coordenada, rua, label ou ID de mapa está embutido no resolvedor.
`--search-graphml` permite reutilizar uma rede ampla OSMnx local em EPSG:4326;
os recortes finais continuam sendo construídos pela rotina de mapas do projeto.

## Complexos viários e escolha por direção

O ponto A do mapa 2 preserva os dois membros indicados pelo usuário:

```json
{
  "label": "A",
  "intersection": "Av. Mario Covas x Rod. dos Tamoios",
  "type": "junction_group",
  "nodes": [
    {"label": "A1", "latitude": -23.2485281, "longitude": -45.8581007, "node_id": 1425156870},
    {"label": "A2", "latitude": -23.2466214, "longitude": -45.8626501, "node_id": 1425164988}
  ]
}
```

Os IDs listados em `nodes` precisam ser confirmados entre os candidatos da
interseção. Um grupo sem membros previamente listados preserva todos os candidatos
encontrados, exigindo pelo menos dois. Nenhum membro vira um ponto O-D adicional.

Após construir o grafo dirigido, o resolvedor compara todos os pares de membros
e propõe o caminho mais curto **em metros**, respeitando os sentidos das arestas.
Não usa tempos BPR nem fluxos. Empates de até 5 m ficam `AMBIGUOUS`; quando todas
as rotas já possuem caminho, essa ambiguidade exige revisão em vez de expandir
automaticamente o raio. Uma escolha explícita em `origin_node`/`destination_node`
é respeitada e precisa pertencer ao grupo e possuir caminho dirigido.

Na verificação OSM desta implementação, as propostas foram:

| Sentido | Membro proposto | Distância dirigida | Alternativa conectada |
| --- | --- | --- | --- |
| A → B | Origem A2, nó 1425164988 | 5.603,9 m | A1: 10.184,1 m |
| B → A | Destino A1, nó 1425156870 | 6.231,7 m | A2: 10.779,1 m |

As duas alternativas são conectadas; a diferença decorre dos sentidos e acessos
do grafo. As escolhas estão salvas nas rotas, com os candidatos e as arestas
locais usadas para gerar as setas do zoom. São propostas para validação visual.
Não representam rotas fixas para o futuro equilíbrio: o solver continua livre
para atribuir fluxos aos caminhos da rede entre os nós O-D escolhidos.

## Centro, raio, snap e reprodutibilidade

O centro é a média das coordenadas de todos os membros físicos. O raio inicial
é a maior distância geodésica até esse centro mais `margin_m` (1000 m no TCC).
O resolvedor recalcula esses campos mesmo quando a entrada contém valores antigos.

Em cada tentativa, reassocia as coordenadas por `nearest_nodes` em CRS métrico e
confere todos os sentidos definidos em `routes`. Aumenta o raio em 500 m se houver
snap excessivo ou rota desconectada, até 15 km. Preserva as componentes do grafo;
não substitui O-D reais por nós da maior componente fortemente conectada.
Dois membros de um grupo não podem colapsar no mesmo nó.

Os status dos pontos são `RESOLVED`, `AMBIGUOUS`, `NOT_FOUND` e `SNAP_TOO_FAR`.
O status do mapa registra ainda `INCOMPLETE`, `ROUTES_DISCONNECTED`,
`AMBIGUOUS_ROUTES`, `RADIUS_LIMIT` ou `ERROR`. Um mapa incompleto impede o uso
experimental por `prepare`/`run`, mesmo que algumas coordenadas estejam presentes.

Os limites podem ser definidos na raiz do JSON:

```json
"point_resolution": {
  "maximum_intersection_error_m": 100,
  "candidate_cluster_m": 100,
  "radius_step_m": 500,
  "max_radius_m": 15000,
  "search_radius_m": 15000,
  "zoom_radius_m": 300
}
```

`max_snap_distance_m` permanece por mapa (300 m no TCC).
`--maximum-intersection-error-m`, `--radius-step-m` e `--max-radius-m` sobrescrevem
os respectivos valores nessa execução. Erro de resolução mede a proximidade
do nó às vias; snap mede o deslocamento da coordenada salva até o nó da rede final.

As coordenadas permanecem junto dos IDs. Para reconstruir a rede posteriormente,
`prepare` pode reassociar pelos locais salvos e atualizar os IDs das rotas, desde
que `graphml` e `graph_sha256` tenham sido removidos explicitamente da configuração.
Em snapshots congelados, a verificação exige hash e IDs idênticos. Uma reconstrução
não substitui a revisão visual caso os acessos ou sentidos tenham mudado.

## Verificação realizada

Foram resolvidos oito pontos conceituais, com nove nós físicos, e conferidos os
12 sentidos previstos. Raios finais: mapa 1 = 4.386 m, mapa 2 = 4.537 m, mapa 3 =
2.834 m. Não foi necessário ampliar os raios iniciais nessa execução. Todos os
snaps foram 0 m. O ponto B do mapa 1 usou aproximação de 11,72 m entre vias com
ligação local; os demais tiveram erro de resolução zero. Nenhum ponto ficou
pendente. Esses valores descrevem o snapshot verificado, não uma garantia sobre
futuras versões dos dados OSM. A bateria real de Braess não foi executada.

Os testes unitários usam redes sintéticas locais, sem Nominatim/Overpass:

```bash
python -m pytest -q
```

Cobrem normalização, aliases, candidatos, viadutos desconectados, grupos,
sentidos distintos, empates, centro/raio, expansão, limites de snap, mudança de
IDs, backups, JSON/CSV/PNGs e continuidade diante de pontos não encontrados.
O teste de resolução impede chamadas ao Frank-Wolfe com um mock que falha.

Arquivos centrais da implementação: `resolve_tcc_points.py`,
`braess/point_resolution.py`, `braess/point_resolution_workflow.py`,
`braess/point_resolution_plots.py` e `tests/test_point_resolution.py`.
`experiment_config.py`, `experiment_maps.py`, `experiments.py` e o CLI antigo
passam a compreender membros de grupos e nós explícitos por direção.
