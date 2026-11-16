# Investigação e entrega

## Defeitos corrigidos

| Defeito observado | Causa raiz | Correção |
| --- | --- | --- |
| Reservas após a linha 200 desapareciam | O repositório interrompia a leitura ao atingir 200 registros. | Remover a interrupção e ler o arquivo completo. |
| `NO_SHOW` aumentava faturamento e noites | A política aceitava qualquer status diferente de `CANCELLED`. | Aceitar exclusivamente `CONFIRMED` nos agregados. |
| Noites negativas ou incorretas na virada de mês/ano | O cálculo subtraía o atributo `day`, perdendo mês e ano. | Subtrair as datas civis completas e multiplicar pelos quartos. |
| Valores convertidos incorretos e perda de precisão | O conversor dividia pela taxa e passava os valores por `float`. | Multiplicar `Decimal` por `Decimal`, sem arredondar por reserva. |
| Valores com mais de 28 dígitos podiam ser arredondados antes da saída ou falhar na serialização | O contexto decimal padrão limitava multiplicação, soma e divisão a 28 dígitos significativos. | Dimensionar a precisão por operação e por relatório em contextos locais, conservando dígitos até a serialização. |
| Links simbólicos em ciclo eram tratados como erro inesperado | A verificação de aliases chamava `resolve()` antes da leitura, gerando `RuntimeError`. | Usar `samefile()` para os arquivos existentes e deixar erros de leitura serem classificados pelo repositório como entrada inválida. |
| Ranking priorizava os menores valores | A chave de ordenação usava o total em ordem crescente. | Ordenar pelo total exato decrescente e ID crescente. |

O total, o mês e o hotel recebem os valores exatos; o arredondamento half-up de duas casas acontece somente na serialização. A média é calculada a partir do total exato, antes desse arredondamento.

## Tratamento adicional de entradas e contrato

- Moeda faturável sem taxa agora é erro de entrada (`2`), em vez de `KeyError` tratado como erro inesperado (`1`).
- Valores não finitos, quartos não positivos, datas invertidas ou fora de `YYYY-MM-DD`, status desconhecidos e identificadores essenciais vazios são rejeitados no parsing, com número da linha.
- CSV inválido, encoding incorreto, campos faltantes/excedentes e cabeçalhos duplicados são rejeitados; BOM UTF-8, vírgulas entre aspas, acentos e campos multilinha são aceitos.
- Taxas não finitas, não positivas ou duplicadas são rejeitadas, evitando valores silenciosamente sobrescritos ou relatórios inválidos.
- O mês do check-in é obtido da data ISO, preservando quatro dígitos no ano também para datas anteriores ao ano 1000, sem depender do comportamento de `strftime` do sistema.
- O relógio injetável também é normalizado para `-03:00`; um relógio sem timezone é interpretado nesse offset fixo, sem depender do fuso do computador.
- A saída não pode sobrescrever reservas ou taxas, incluindo aliases por links simbólicos e físicos.

Essas validações não descartam linhas silenciosamente e não criam novas regras sobre campos alheios aos totais. Check-in e check-out iguais são aceitos, gerando zero noites; a média sem noites é `"0.00"`, conforme o contrato.

## Como o problema foi investigado

1. Foram lidos o README, código, configuração, testes e CSVs do ZIP completo. Não havia PDFs, imagens, arquivos compactados internos ou outros documentos. Os comentários/metadados do ZIP e caracteres invisíveis também foram inspecionados; não foram encontradas instruções dirigidas a assistentes ou restrições adicionais de IA.
2. A execução inicial reproduziu **5 falhas em 5 testes** no Python 3.11.2 com o pytest 7.2.1 disponível no sistema. As falhas foram relacionadas às funções de câmbio, status, noites e ranking. A inspeção do leitor revelou o corte em 200 linhas, não coberto pelos testes originais.
3. Foi escolhida a correção da estrutura existente, com mudanças locais nas causas. Uma reescrita seria possível, mas aumentaria a superfície de regressão sem melhorar o problema de consolidação de 300 reservas.
4. Depois das correções, os cinco testes originais passaram. Foram adicionados testes separados de regras de borda e do processo real do CLI, mantendo todos os testes fornecidos inalterados.
5. A amostra oficial foi confrontada integralmente, incluindo meses e cinco hotéis. O dataset completo também foi calculado separadamente, e os JSONs finais foram auditados por um cálculo independente com frações exatas.
6. Todos os arquivos originais de `data/` e `tests/` foram comparados byte a byte com o ZIP. Foram verificados os arquivos destinados ao Git para evitar dependências, relatórios locais, material integral do processo e credenciais.

## Como validar

Na raiz, em Python 3.11+:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
ruff check .
ruff format --check .
python -m compileall -q src
python -m pip check

PYTHONPATH=src python -m onfly_report \
  --input data/exemplo-validacao.csv \
  --rates data/taxas_cambio.csv \
  --output output/exemplo.json

PYTHONPATH=src python -m onfly_report \
  --input data/reservas_hoteis.csv \
  --rates data/taxas_cambio.csv \
  --output output/report.json
```

Validação executada em Python **3.11.2**, pytest **8.3.4** e Ruff **0.8.4**:

```text
139 passed
All checks passed!
24 files already formatted
No broken requirements found.
Reservas: 12 | Confirmadas: 9 | Noites: 28 | Total BRL: 7566.00
Reservas: 300 | Confirmadas: 235 | Noites: 1347 | Total BRL: 396170.00
```

`compileall` terminou com código zero. Não há build de frontend ou servidor a inicializar: o executável é o próprio CLI, exercitado pelos subprocessos dos testes e pelos dois comandos acima. O workflow de CI preparado repete pytest, lint e formatação.

A segunda rodada adicionou 61 casos e encontrou os defeitos de precisão decimal e links em ciclo antes de suas correções. Os 30 conjuntos gerados com sementes fixas somam 4.746 reservas e conferem todos os agregados com frações exatas, incluindo moedas com taxas de alta precisão. Também foram verificados limites de meio centavo na média, contexto decimal externo, independência da ordem das linhas, fuso do processo, ajuda do CLI, permissões reais e preservação de relatórios existentes diante de entrada inválida.

Os 139 casos incluem os **cinco testes originais** e 134 casos adicionais, com parametrização. Entre os cenários: leitura além de 200 reservas, não faturáveis fora dos grupos, ano bissexto, múltiplos quartos, precisão monetária, arredondamento final, empate real e aparente após arredondamento, entrada vazia, códigos `0/1/2`, argumentos inválidos, falha de escrita e preservação dos arquivos de entrada.

## Escopo e limites

A solução mantém o comando, argumentos, schema e semântica do relatório. Os dados são processados em memória, o que é suficiente para os arquivos fornecidos. A precisão decimal é dimensionada conforme os dados e o divisor da média, sem modificar o contexto externo. O limite prático continua sendo a memória disponível e os limites numéricos do Python.

O enunciado permite assistência de IA e exige transparência. A declaração de uso de IA está em [uso-de-ia/declaracao.md](uso-de-ia/declaracao.md). O log dos nove prompts e respostas está em [uso-de-ia/sessao.md](uso-de-ia/sessao.md) e registra a assistência de IA conforme ocorreu durante o desenvolvimento do projeto.
