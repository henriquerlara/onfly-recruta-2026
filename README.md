# Onfly — Consolidador de reservas de hotel

CLI em Python 3.11 que lê reservas e taxas de câmbio em CSV e gera um relatório JSON com contagens por status, noites de quarto, valores em BRL, consolidação por mês de check-in e ranking de hotéis. Solução do desafio Recruta Onfly 2026, a partir do projeto fornecido.

## Executar

O CLI usa somente a biblioteca padrão. Na raiz do projeto:

```bash
PYTHONPATH=src python3.11 -m onfly_report \
  --input data/reservas_hoteis.csv \
  --rates data/taxas_cambio.csv \
  --output output/report.json \
  --top 5
```

O diretório de saída é criado automaticamente. O resumo vai para stdout; erros vão para stderr. O JSON completo fica em `output/report.json`.

| Argumento | Obrigatório | Padrão |
| --- | --- | --- |
| `--input` | Sim | — |
| `--rates` | Sim | — |
| `--output` | Não | `output/report.json` |
| `--top` | Não | `5`, inteiro ≥ 1 |

Códigos de saída: `0` para sucesso, `2` para entrada ou argumento inválido e `1` para erro inesperado ou falha de escrita. A saída não pode apontar para um arquivo de entrada, inclusive por links.

Não há serviços externos, banco de dados ou variáveis de ambiente a configurar. `PYTHONPATH=src` permite executar o pacote diretamente, sem instalação.

## Regras de consolidação

- Todas as reservas são lidas, convertidas e contadas por status; apenas `CONFIRMED` entra nos valores, noites, meses e hotéis.
- Noites de quarto = diferença não inclusiva entre check-out e check-in × quartos.
- O valor da reserva é multiplicado pela taxa para BRL; ele já é o valor total, portanto não é multiplicado novamente pelos quartos.
- Valores são calculados com `Decimal` e arredondados somente ao serializar, para duas casas com half-up. A média usa o total exato dividido pelas noites de quarto.
- Cada reserva confirmada pertence integralmente ao mês de seu check-in. Os meses são crescentes; os hotéis são ordenados por valor exato decrescente e, no empate, por ID crescente.
- Dinheiro é string com duas casas; contagens são inteiros; `report_version` é `"1.0"` e `generated_at` usa offset fixo `-03:00`.

Entradas malformadas interrompem a geração em vez de serem ignoradas. Há validação de cabeçalhos, estrutura CSV, datas `YYYY-MM-DD`, status, quartos positivos, valores finitos não negativos e taxas finitas positivas sem moeda duplicada. Datas iguais são aceitas: produzem zero noites e, sem noites no total, média `"0.00"`. Datas invertidas são rejeitadas. Não são impostas regras sobre campos sem efeito no relatório, como pagamento e horário da compra.

## Testes e qualidade

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
ruff check .
ruff format --check .
```

As versões de pytest e Ruff estão fixadas em `requirements-dev.txt`. A execução validada em Python 3.11.2 teve **139 testes aprovados**, incluindo os cinco originais, preservados sem alterações. A CI executa os mesmos testes e verificações em Python 3.11.

Há 30 conjuntos gerados com sementes fixas, totalizando 4.746 reservas, cujos relatórios completos são comparados a uma referência independente com frações exatas. Os testes adicionais também cobrem a amostra oficial completa, o dataset de 300 linhas, frações de centavo, precisão acima do limite de inteiros de `float`, média antes do arredondamento, desempates, calendário, entrada vazia, não faturáveis e o processo real do CLI com seus códigos de saída. Veja a investigação em [entrega/README-ENTREGA.md](entrega/README-ENTREGA.md).

## Conferência rápida

```bash
PYTHONPATH=src python3.11 -m onfly_report \
  --input data/exemplo-validacao.csv \
  --rates data/taxas_cambio.csv \
  --output output/exemplo.json
```

| Entrada | Reservas | Confirmadas | Canceladas | No-show | Noites de quarto | Total BRL | Média BRL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Amostra de validação | 12 | 9 | 2 | 1 | 28 | 7566.00 | 270.21 |
| Dataset completo | 300 | 235 | 31 | 34 | 1347 | 396170.00 | 294.11 |

## Organização e decisões

```text
src/onfly_report/
  cli.py                 argumentos, execução e saída
  models.py              linhas cruas e reservas tipadas
  repositories/          leitura dos dois CSVs
  services/              parsing, status, noites, câmbio e relatório
tests/                  testes fornecidos e regressões adicionais
data/                   CSVs fornecidos, preservados
entrega/                investigação e declaração/registro de IA exigidos
output/                 relatórios locais, ignorados pelo Git
```

Foi mantida a organização do projeto inicial: as correções ficam próximas de suas causas e não exigem frameworks nem novas dependências de execução. Reescrever o CLI ou introduzir processamento distribuído não traria benefício para este volume. As reservas ficam em memória; para exportações muito maiores, leitura incremental seria uma melhoria futura. A precisão de `Decimal` é dimensionada conforme os coeficientes, as escalas dos valores, o número de parcelas e o divisor da média, dentro de contextos locais. Isso evita arredondamento intermediário pelo limite padrão de 28 dígitos sem alterar o contexto de quem chama o código. O volume e as escalas numéricas continuam sujeitos à memória disponível e aos limites do Python.

## Entrega

O enunciado autoriza publicar o projeto fornecido, incluindo seus dados e testes. O ZIP e documentos integrais do processo não são versionados. Os arquivos exigidos de uso de IA estão em [entrega/uso-de-ia/](entrega/uso-de-ia/), com a atribuição real das atividades.
