# Modelo computacional do Paradoxo de Braess

> Documento técnico interno para orientar a escrita do Capítulo 2 e a apresentação do software.
>
> Este arquivo descreve **como o software funciona, por que cada decisão foi tomada e quais alternativas foram descartadas**.
>
> **Não contém resultados experimentais da pesquisa.** Resultados, comparação entre cenários, possíveis ocorrências do paradoxo e interpretação dos dados devem permanecer no Capítulo 3.

---

# 1. Objetivo do software

O software foi desenvolvido para modelar uma rede viária urbana, distribuir uma demanda de veículos sobre essa rede até obter uma aproximação do equilíbrio do usuário de Wardrop e, posteriormente, testar alterações na topologia da rede.

O fluxo conceitual é:

```text
dados viários
    ↓
MultiDiGraph
    ↓
pré-processamento das arestas
    ↓
tempo de fluxo livre + capacidade
    ↓
função de custo
    ↓
demanda origem-destino
    ↓
menores caminhos
    ↓
All-or-Nothing
    ↓
Frank-Wolfe
    ↓
aproximação do equilíbrio de Wardrop
    ↓
remoção de conexão
    ↓
novo equilíbrio
    ↓
comparação dos cenários
```

O software não é um simulador microscópico de carros individuais. Ele realiza uma **atribuição estática de tráfego**: trabalha com fluxos agregados de veículos por aresta.

Essa escolha foi feita porque o objetivo do trabalho é estudar o efeito da **estrutura da rede sobre o equilíbrio de tráfego**, e não reproduzir aceleração, frenagem, filas individuais, comportamento de semáforos ou interação veículo a veículo.

---

# 2. Organização geral do código

A implementação foi dividida por responsabilidade.

Uma organização típica do projeto é:

```text
braess/
├── models.py
├── costs.py
├── synthetic.py
├── routing.py
├── assignment.py
├── metrics.py
├── frank_wolfe.py
├── urban.py
├── visualization.py
├── outputs.py
└── removal.py

run_synthetic.py
run_urban.py
run_removal.py

tests/
├── test_costs.py
├── test_routing.py
├── test_assignment.py
├── test_metrics.py
├── test_frank_wolfe.py
├── test_urban.py
├── test_bpr_mapping.py
└── test_removal.py
```

A intenção dessa separação é evitar que aquisição de dados, matemática, roteamento, otimização, visualização e experimentos fiquem misturados em um único script.

Isso facilita:

- testar cada parte isoladamente;
- substituir um modelo sem alterar o restante;
- localizar erros;
- explicar o software;
- manter rastreabilidade metodológica.

---

# 3. Por que representar a cidade como grafo

A rede viária é representada como:

$$
G = (V,E)
$$

em que:

- $V$ representa o conjunto de vértices;
- $E$ representa o conjunto de arestas.

No contexto urbano:

- vértices representam interseções e pontos relevantes;
- arestas representam segmentos de rua.

Esse modelo permite aplicar diretamente algoritmos clássicos de teoria dos grafos, como Dijkstra.

---

# 4. Por que usar `MultiDiGraph`

O código utiliza:

```python
networkx.MultiDiGraph
```

em vez de `Graph` ou `DiGraph`.

## 4.1 Por que direcionado

Uma rua pode ser de mão única.

Portanto:

```text
A → B
```

não implica necessariamente:

```text
B → A
```

Um `DiGraph` ou `MultiDiGraph` preserva essa diferença.

## 4.2 Por que múltiplas arestas

Podem existir duas ou mais conexões entre os mesmos nós.

Exemplo:

```text
A → B, key=0
A → B, key=1
```

Essas arestas podem representar pistas paralelas, alças, acessos, segmentos distintos ou vias diferentes que ligam os mesmos pontos.

Por isso, uma aresta é identificada por:

```text
(u, v, key)
```

e não apenas por:

```text
(u, v)
```

## 4.3 Por que não converter para `DiGraph`

A versão inicial do projeto convertia o grafo para `DiGraph` para facilitar algumas análises.

Essa abordagem foi abandonada no núcleo científico porque a conversão elimina a distinção entre arestas paralelas.

Para uma pesquisa que depende de remover conexões e atribuir fluxo corretamente, essa perda de informação não é desejável.

---

# 5. `EdgeId`

O arquivo `models.py` define:

```python
@dataclass(frozen=True, slots=True)
class EdgeId:
    u: NodeId
    v: NodeId
    key: Hashable
```

Essa estrutura identifica uma aresta completa.

O código utiliza `EdgeId` como chave nos mapas de fluxo:

```python
flows: dict[EdgeId, float]
```

Por exemplo:

```python
flows[EdgeId(100, 200, 0)] = 1200.0
```

significa que aquela aresta recebeu fluxo de 1200 veículos na unidade temporal adotada.

## Por que `frozen=True`

A identidade de uma aresta não deve mudar depois de criada.

Além disso, objetos imutáveis podem ser usados com segurança como chave em dicionários.

## Por que `slots=True`

Evita a criação arbitrária de atributos e reduz o custo de memória dos objetos.

Não é uma exigência matemática, mas melhora a consistência da implementação.

---

# 6. Pares origem-destino

A demanda é representada por:

```python
ODPair(
    origin=...,
    destination=...,
    demand=...
)
```

OD significa **Origin-Destination**.

Matematicamente, a demanda entre uma origem $o$ e um destino $d$ pode ser representada por:

$$
q_{od}
$$

O solver pode receber vários pares OD, não apenas um.

---

# 7. Fonte da rede urbana

A rede urbana é obtida do OpenStreetMap por meio do OSMnx.

O OSMnx fornece um `MultiDiGraph` contendo atributos como:

- `length`;
- `highway`;
- `lanes`;
- `maxspeed`;
- `speed_kph`;
- `travel_time`;
- `name`.

Nem todos esses atributos aparecem em todas as arestas.

Por isso existe uma etapa de pré-processamento.

---

# 8. Por que OpenStreetMap e OSMnx

Foram escolhidos porque permitem obter dados viários abertos, preservar a geometria real da rede, trabalhar com sentidos de circulação, manter arestas paralelas, acessar comprimento e classificação das vias e integrar diretamente a rede ao NetworkX.

Uma alternativa seria construir manualmente o grafo da região.

Essa opção foi descartada porque seria mais sujeita a erro, difícil de reproduzir, trabalhosa, menos atualizável e menos escalável.

---

# 9. Componente fortemente conectada

Antes de executar o solver urbano, o código seleciona a maior componente fortemente conectada.

Uma componente fortemente conectada tem a propriedade de que, para quaisquer dois nós $u$ e $v$ dentro dela, existe caminho direcionado de $u$ para $v$ e também de $v$ para $u$.

Essa etapa reduz problemas causados por partes isoladas ou por recortes da rede em que determinadas viagens são impossíveis.

---

# 10. Tempo de fluxo livre

Cada aresta possui um tempo de percurso em condições de fluxo livre:

$$
t_e^0
$$

No código:

```text
free_flow_time
```

Conceitualmente:

$$
t_e^0 = \frac{l_e}{v_e}
$$

em que:

- $l_e$ é o comprimento da aresta;
- $v_e$ é sua velocidade estimada sem congestionamento.

O OSMnx fornece inicialmente um atributo `travel_time`.

Durante o pré-processamento urbano, esse valor é preservado como `free_flow_time`, e `travel_time` passa a representar o custo atual da aresta.

---

# 11. Classificação `highway`

O OpenStreetMap utiliza o atributo `highway` para indicar a função da via na rede.

Uma hierarquia conceitual aproximada é:

```text
motorway
    ↓
trunk
    ↓
primary
    ↓
secondary
    ↓
tertiary
    ↓
unclassified / residential
    ↓
service
```

Essa classificação é funcional. Não deve ser interpretada apenas por número de faixas.

---

# 12. Significado das classes principais

## `motorway`

Via de alto desempenho e grande importância, normalmente com maior controle de acesso.

## `trunk`

Via de grande importância ou desempenho, mas não necessariamente uma `motorway`.

## `primary`

Um dos principais eixos da rede.

## `secondary`

Via importante na distribuição do tráfego, hierarquicamente abaixo de `primary`.

## `tertiary`

Via de conexão entre áreas menores ou bairros, normalmente alimentando vias mais importantes.

## `residential`

Via predominantemente destinada a acesso local em áreas residenciais.

## `unclassified`

Não significa "sem classificação". É uma categoria funcional de via pública de menor importância que `tertiary`, quando nenhuma categoria mais específica se aplica.

## `service`

Via de acesso local a estacionamentos, estabelecimentos, áreas internas ou instalações.

---

# 13. Tipos `_link`

Exemplos:

```text
motorway_link
primary_link
secondary_link
tertiary_link
```

São alças, acessos ou ligações associadas às respectivas classes principais.

---

# 14. Normalização de `lanes`

O OpenStreetMap pode retornar `lanes` de formas diferentes:

```text
2
"2"
"2;3"
["1", "2"]
None
```

O código transforma essas representações em um inteiro.

Quando existem vários valores válidos, atualmente utiliza o maior valor encontrado.

Quando não existe valor utilizável, usa-se um número padrão de faixas.

Essa decisão deve ser registrada como simplificação metodológica.

---

# 15. Capacidade da aresta

A função de congestionamento precisa da capacidade:

$$
c_e
$$

O modelo atual estima:

$$
c_e = c_{faixa} \cdot n_{faixas}
$$

em que:

- $c_{faixa}$ é uma capacidade por faixa associada ao tipo de via;
- $n_{faixas}$ é o número de faixas.

O código guarda:

```text
capacity
capacity_source
```

para manter rastreabilidade.

---

# 16. Função de custo

O tempo de uma rua depende do fluxo:

$$
t_e = t_e(x_e)
$$

O projeto implementa duas funções:

1. função linear;
2. função BPR.

---

# 17. Função linear

A função linear é:

$$
t_e(x_e) = \alpha_e + \beta_e x_e
$$

Ela é usada apenas na rede sintética de validação.

Foi mantida porque o exemplo teórico do Paradoxo de Braess apresentado no trabalho utiliza funções dessa forma.

Não é o principal modelo da rede urbana.

---

# 18. Função BPR

Para a aplicação urbana é usada:

$$
t_e(x_e)
=
t_e^0
\left[
1 +
\alpha
\left(
\frac{x_e}{c_e}
\right)^\beta
\right]
$$

em que:

- $t_e^0$ = tempo de fluxo livre;
- $x_e$ = fluxo da aresta;
- $c_e$ = capacidade;
- $\alpha$ e $\beta$ = parâmetros da curva.

---

# 19. Por que BPR e não função linear na cidade

A função linear é adequada ao exemplo teórico por ser simples e permitir interpretação analítica.

Na rede urbana é desejável considerar explicitamente a razão:

$$
\frac{x}{c}
$$

entre fluxo e capacidade.

A BPR faz isso e permite crescimento não linear do atraso.

---

# 20. Parâmetros BPR adotados

Os parâmetros adotados vêm de uma calibração reportada em artigo científico.

| Categoria | $\alpha$ | $\beta$ |
|---|---:|---:|
| Motorways | 0.65625 | 4.8 |
| Urban arterials | 1.0 | 1.5 |
| Urban streets | 1.28571 | 1.0 |

IMPORTANTE:

Esses parâmetros **não foram calibrados com dados de São José dos Campos**.

A forma correta de escrever é:

> Foram adotados parâmetros da função BPR previamente calibrados e reportados na literatura.

---

# 21. Mapeamento OSM → categorias BPR

O OpenStreetMap e o artigo usam taxonomias diferentes.

O software define uma correspondência explícita.

## Motorways

```text
motorway
motorway_link
```

recebem:

```text
categoria = motorways
alpha = 0.65625
beta = 4.8
```

## Urban arterials

```text
trunk
trunk_link
primary
primary_link
secondary
secondary_link
```

recebem:

```text
categoria = urban_arterials
alpha = 1.0
beta = 1.5
```

## Urban streets

```text
tertiary
tertiary_link
residential
living_street
unclassified
service
```

recebem:

```text
categoria = urban_streets
alpha = 1.28571
beta = 1.0
```

Esse mapeamento é uma decisão metodológica do trabalho. Os valores de $\alpha$ e $\beta$ vêm do artigo; a correspondência com as classes OSM foi definida na implementação.

---

# 22. `CostFunction`

O software usa uma interface comum para funções de custo.

Uma função deve implementar:

```python
travel_time(flow)
integral(flow)
```

Isso permite que o Frank-Wolfe não dependa diretamente da BPR ou da função linear.

---

# 23. Por que existe `integral()`

O Frank-Wolfe é aplicado à formulação de Beckmann:

$$
Z(x)
=
\sum_{e\in E}
\int_0^{x_e}
t_e(w)
\,dw
$$

Por isso o solver precisa da integral da função de custo.

---

# 24. Equilíbrio de Wardrop

O software procura uma aproximação do primeiro princípio de Wardrop.

No equilíbrio, nenhum usuário consegue obter uma melhora significativa no próprio custo mudando unilateralmente para outra rota disponível.

O software não calcula necessariamente o equilíbrio exato. Ele calcula uma aproximação numérica.

---

# 25. Por que não simular motorista por motorista

Uma simulação microscópica exigiria regras de comportamento individual, mais processamento e tratamento de ordem de atualização.

Como o problema é de equilíbrio estático de fluxo, o Frank-Wolfe é mais apropriado e matematicamente estruturado.

---

# 26. Dijkstra

O menor caminho é calculado usando Dijkstra.

O peso utilizado é:

```text
travel_time
```

Portanto, o algoritmo procura a rota de menor tempo atual, não a de menor distância ou menor número de ruas.

Como `travel_time` muda com o fluxo, o menor caminho também pode mudar entre iterações.

---

# 27. Dijkstra e arestas paralelas

O NetworkX normalmente retorna uma sequência de nós.

Em um `MultiDiGraph`, isso não identifica qual aresta paralela foi usada.

Por isso o código converte a rota para:

```python
[
    EdgeId(A, B, key_1),
    EdgeId(B, C, key_2),
]
```

preservando a `key`.

---

# 28. All-or-Nothing Assignment

Para cada par OD:

1. calcula o menor caminho;
2. coloca toda a demanda nesse caminho;
3. acumula os fluxos.

O resultado é um vetor auxiliar e **não é o equilíbrio final**.

---

# 29. Frank-Wolfe

O Frank-Wolfe é o solver principal.

Cada iteração executa:

```text
1. atualizar tempos das arestas
2. calcular métricas
3. verificar convergência
4. executar All-or-Nothing
5. calcular direção
6. procurar tamanho de passo
7. atualizar fluxos
```

---

# 30. Vetor atual e vetor auxiliar

Seja $x$ o vetor de fluxo atual e $y$ o vetor produzido pelo All-or-Nothing.

A direção é:

$$
d = y - x
$$

---

# 31. Atualização do fluxo

A atualização é:

$$
x^{(k+1)}
=
x^{(k)}
+
\lambda_k
\left(
y^{(k)} - x^{(k)}
\right)
$$

com:

$$
0 \leq \lambda_k \leq 1
$$

---

# 32. Significado de $\lambda$

$\lambda$ controla quanto o solver se move em direção ao fluxo auxiliar.

- $\lambda = 0$: nenhuma mudança;
- $\lambda = 1$: adoção completa do fluxo auxiliar;
- valores intermediários: combinação dos dois estados.

---

# 33. Line search

O software usa:

```python
scipy.optimize.minimize_scalar
```

para encontrar o $\lambda$ que minimiza a função de Beckmann naquela direção.

Essa escolha evita usar um passo arbitrário.

---

# 34. TSTT

O Total System Travel Time é:

$$
TSTT
=
\sum_{e\in E}
x_e t_e(x_e)
$$

Ele representa o custo agregado da rede.

---

# 35. Tempo médio

O tempo médio é:

$$
\bar{T}
=
\frac{
TSTT
}{
\sum q_{od}
}
$$

---

# 36. SPTT

O Shortest Path Total Travel Time é:

$$
SPTT
=
\sum_{(o,d)}
q_{od}\pi_{od}
$$

em que $\pi_{od}$ é o custo do menor caminho atual.

---

# 37. Relative Gap

O código utiliza:

$$
RG
=
\frac{
TSTT - SPTT
}{
TSTT
}
$$

para medir proximidade do equilíbrio.

Quanto menor o `Relative Gap`, mais próxima está a solução.

---

# 38. Critério de convergência

O solver para quando:

$$
RG \leq \varepsilon
$$

onde $\varepsilon$ é a tolerância definida.

`converged = True` significa que a solução atingiu essa tolerância.

A forma correta de escrever é:

> O algoritmo convergiu para uma aproximação numérica do equilíbrio de Wardrop dentro da tolerância adotada.

---

# 39. Histórico do Frank-Wolfe

Cada iteração registra:

```text
iteration
relative_gap
step_size
beckmann_objective
total_system_travel_time
```

Esses dados permitem acompanhar e auditar o solver.

---

# 40. Rede sintética

O arquivo `synthetic.py` cria uma rede artificial usada somente para validação do software.

Ela testa conjuntamente:

- funções de custo;
- roteamento;
- All-or-Nothing;
- Frank-Wolfe;
- métricas;
- remoção.

Ela não representa São José dos Campos.

---

# 41. Pré-processamento urbano

O `urban.py` executa:

```text
ler atributos OSM
↓
normalizar highway
↓
normalizar lanes
↓
obter free_flow_time
↓
calcular capacidade
↓
determinar categoria BPR
↓
obter alpha e beta
↓
criar BPRCost
↓
inicializar travel_time
```

---

# 42. Visualização

O software possui visualização separada do solver.

No mapa:

- espessura representa fluxo;
- cor representa relação fluxo/capacidade.

A camada visual não interfere nos cálculos.

---

# 43. Por que filtrar fluxos pequenos no mapa

O Frank-Wolfe combina soluções sucessivas e pode deixar resíduos muito pequenos em algumas arestas.

O filtro visual evita que esses resíduos poluam o mapa.

Ele não remove fluxo do solver.

---

# 44. Exportação

O software exporta dados para inspeção.

Arquivos principais:

```text
edge-results.csv
iterations.csv
summary.json
removal-results.csv
```

`edge-results.csv` também registra categoria BPR, $\alpha$, $\beta$, capacidade e fonte da capacidade de cada aresta.

---

# 45. Remoção de conexões

O módulo `removal.py` executa:

```text
equilíbrio original
↓
seleção de candidata
↓
cópia do grafo
↓
remoção da aresta
↓
checagem de conectividade
↓
novo equilíbrio
↓
comparação
```

---

# 46. Por que copiar o grafo

Cada cenário precisa ser independente.

Modificar o grafo original contaminaria os experimentos seguintes.

Por isso cada remoção usa uma cópia.

---

# 47. Checagem de conectividade

Antes de recalcular o equilíbrio, o software verifica se todos os pares OD ainda possuem caminho.

Uma remoção que impossibilita uma demanda é tratada como cenário inválido para aquela comparação.

---

# 48. Seleção de candidatas

O protótipo pode priorizar arestas com maior fluxo.

Isso reduz o espaço de busca.

Alta utilização não significa Paradoxo de Braess; é apenas um filtro computacional.

---

# 49. Comparação após remoção

A melhoria absoluta é:

$$
\Delta T
=
TSTT_{original}
-
TSTT_{modificado}
$$

A melhoria relativa é:

$$
I
=
\frac{
TSTT_{original}
-
TSTT_{modificado}
}{
TSTT_{original}
}
$$

O detector ainda exige convergência e conectividade.

---

# 50. Unidade de remoção atual

A unidade básica é:

```text
(u, v, key)
```

ou seja, uma aresta direcionada.

Uma rua física pode ser formada por várias arestas. Nos experimentos finais isso pode precisar ser agrupado.

---

# 51. Testes automatizados

O projeto utiliza `pytest`.

Os testes cobrem:

- LinearCost;
- BPRCost;
- integrais;
- fluxo negativo;
- rede sintética;
- Dijkstra;
- arestas paralelas;
- All-or-Nothing;
- TSTT;
- Relative Gap;
- Frank-Wolfe;
- convergência;
- normalização urbana;
- mapeamento BPR;
- remoção;
- preservação do grafo original.

---

# 52. Principais decisões e por que A em vez de B

## `MultiDiGraph` em vez de `DiGraph`

Porque é necessário preservar direção e arestas paralelas.

## OSMnx em vez de grafo manual

Porque fornece rede real, reproduzível e aberta.

## BPR em vez de função linear na cidade

Porque incorpora explicitamente fluxo/capacidade e atraso não linear.

## Parâmetros BPR por categoria em vez de um único par global

Porque tipos diferentes de via têm comportamento funcional diferente e o artigo fornece parâmetros distintos.

## Dijkstra em vez de busca por número de arestas

Porque o custo de interesse é tempo de viagem.

## All-or-Nothing como subproblema

Porque fornece o vetor de fluxo auxiliar exigido pelo Frank-Wolfe.

## Frank-Wolfe em vez de motorista por motorista

Porque o problema é um equilíbrio estático de fluxo com formulação de Beckmann.

## Line search em vez de passo fixo

Porque o tamanho do passo é escolhido de acordo com a função objetivo.

## Relative Gap em vez de apenas número de iterações

Porque convergência deve medir proximidade do equilíbrio, não tempo de execução.

## Cópia do grafo em vez de remoção acumulativa

Porque cada cenário precisa ser independente.

---

# 53. Limitações do software

Registrar metodologicamente:

- atribuição estática;
- ausência de propagação dinâmica de filas;
- semáforos não modelados em detalhe;
- dependência dos dados do OpenStreetMap;
- possíveis valores ausentes de `lanes`;
- capacidade estimada;
- parâmetros BPR provenientes de literatura externa;
- mapeamento OSM → categorias BPR definido no trabalho;
- dependência de dados OD;
- equilíbrio numérico aproximado;
- remoção de aresta como simplificação de uma intervenção viária.

---

# 54. Relação entre módulos

```text
models.py
    estruturas básicas

costs.py
    funções de custo

synthetic.py
    validação controlada

routing.py
    Dijkstra

assignment.py
    All-or-Nothing

metrics.py
    Beckmann, TSTT, tempo médio, gap

frank_wolfe.py
    solver

urban.py
    preparação da rede real

visualization.py
    mapas e gráficos

outputs.py
    CSV e JSON

removal.py
    cenários de alteração da rede
```

---

# 55. Explicação curta para apresentação

> A malha viária é obtida do OpenStreetMap e representada como um MultiDiGraph, preservando sentidos e vias paralelas. Cada segmento recebe um tempo de fluxo livre, uma capacidade e uma função BPR que relaciona fluxo e tempo. A demanda é representada por pares origem-destino. Em cada iteração, Dijkstra encontra os menores caminhos atuais e uma atribuição All-or-Nothing gera um fluxo auxiliar. O Frank-Wolfe combina esse fluxo com o estado atual usando um passo calculado por line search até que o Relative Gap fique abaixo da tolerância, aproximando o equilíbrio de Wardrop. Depois, conexões podem ser removidas e o equilíbrio é recalculado para comparar o custo da rede.

---

# 56. Referências necessárias para o Capítulo 2

Conferir se estão na bibliografia:

- OpenStreetMap;
- OSMnx;
- NetworkX;
- Dijkstra;
- Wardrop;
- Beckmann;
- Frank e Wolfe;
- função BPR;
- artigo dos parâmetros BPR por categoria;
- referência da capacidade por faixa.

---

# 57. O que não entra neste documento

Não colocar aqui:

- resultados numéricos dos experimentos;
- ruas identificadas;
- quantidade de candidatas;
- gráficos finais de resultados;
- análise de sensibilidade dos resultados;
- conclusão sobre existência do paradoxo em São José dos Campos.

Esses elementos pertencem ao Capítulo 3.