# Log de prompts e respostas

Este documento registra os nove prompts e as respostas da assistência de IA durante o desenvolvimento do projeto, incluindo a investigação dos defeitos, as correções, os testes e a revisão da documentação.

O log apresenta os pedidos de apoio e os resultados de cada etapa, conforme ocorreram durante o trabalho.

## 1. Entendimento do projeto

### Prompt

> Dá uma olhada nesse projeto e me ajuda a entender o caminho dos dados até sair o JSON. Quero saber onde ficam as regras principais e o que preciso conferir primeiro.

### Resposta

O ponto de entrada é `src/onfly_report/__main__.py`, que chama `main()` em `cli.py`. O CLI recebe os caminhos de reservas, câmbio e saída, valida `--top`, chama o `ReportBuilder` e grava o JSON. O resumo fica em stdout; os erros ficam em stderr.

Dentro do relatório, o caminho dos dados é:

1. `CsvReservationRepository.read()` lê o CSV e devolve linhas com seus números de origem.
2. `RowParser.parse()` transforma textos em datas civis, inteiros e `Decimal`, produzindo reservas tipadas.
3. `CsvRateRepository.read()` carrega a relação entre moeda e taxa para BRL.
4. `ReportBuilder.build()` conta os status de todas as reservas e seleciona as faturáveis com `is_billable()`.
5. `calculate_room_nights()` calcula as noites de quarto, e `convert_to_brl()` converte o valor.
6. O builder soma os totais e agrupa por mês de check-in e hotel, ordena os grupos e formata o dinheiro na saída.

Eu começaria pelos cinco testes fornecidos e pelas funções pequenas de status, noites e câmbio. Depois conferiria a leitura completa do CSV e a ordenação do ranking. Esses pontos explicam os números errados sem exigir uma reescrita do CLI. Os dados fornecidos e os testes originais devem permanecer intactos.

## 2. Análise das falhas nos testes

### Prompt

> Rodei os testes e queria entender melhor essas falhas. Me explica o que cada uma indica e onde pode estar o problema, sem mexer nos testes que vieram no desafio.

### Resposta

As cinco falhas do projeto original apontam para quatro regras incorretas:

| Teste | Resultado original | Esperado | Onde investigar |
| --- | --- | --- | --- |
| Conversão de moeda | `118.45` | `642.00` | O conversor divide pela taxa e usa `float`. |
| Noites na virada do mês | `-28` | `3` | O cálculo subtrai apenas o dia do mês. |
| Regressão do relatório | Total `1018.45`, média `203.69` | Total `1542.00`, média `308.40` | O câmbio errado se propaga para total e média. |
| Status faturáveis | Total `120.00` | `100.00` | `NO_SHOW` está entrando como faturável. |
| Ranking dos hotéis | `H04`, `H03`, `H02` | `H01`, `H02`, `H03` | A ordenação financeira está crescente. |

Na inspeção do leitor também há um defeito fora desses cinco testes: ele interrompe a leitura quando chega a 200 reservas. O arquivo principal tem 300, então as últimas 100 ficam de fora. Esse caso precisa de um teste adicional em outro arquivo.

As correções devem ficar no código de produção. Os testes fornecidos servem de referência para conferir as regras e não precisam ser alterados.

## 3. Cálculo das noites

### Prompt

> Confere esse cálculo das noites pra mim. Ele precisa funcionar quando a reserva começa num mês e termina em outro, e também considerar a quantidade de quartos. Me mostra o ajuste e explica por que funciona.

### Resposta

O problema está nesta expressão do código original:

```python
(checkout.day - checkin.day) * rooms
```

O atributo `.day` contém somente o número do dia. Para uma estadia de 30 de janeiro a 2 de fevereiro, a subtração vira `2 - 30`, que resulta em `-28`.

O ajuste que aparece na versão atual é:

```python
def calculate_room_nights(checkin: date, checkout: date, rooms: int) -> int:
    return (checkout - checkin).days * rooms
```

Subtrair duas datas produz um `timedelta` que considera mês, ano e ano bissexto. Assim, 30/01 a 02/02 dá três noites; com dois quartos, são seis noites de quarto. Não se soma um dia, porque o check-out não é uma noite adicional.

Os testes adicionais cobrem virada de ano, fevereiro bissexto e múltiplos quartos. Datas iguais produzem zero noites. O parser rejeita datas invertidas e quartos menores que um antes da agregação.

## 4. Câmbio e precisão

### Prompt

> Me ajuda a revisar a parte do câmbio. Pelo enunciado, o valor tem que ser multiplicado pela taxa e usar Decimal. Confere também se tem algum arredondamento acontecendo antes da hora.

### Resposta

O conversor original faz duas coisas que precisam mudar:

```python
return Decimal(str(float(amount) / float(rate)))
```

A operação correta é multiplicar pela taxa para BRL. Passar por `float` também perde a garantia de precisão decimal; converter o resultado de volta para `Decimal` não recupera os dígitos perdidos.

A conversão atual mantém os operandos como `Decimal` e reserva precisão suficiente para o produto:

```python
with localcontext() as context:
    context.prec = max(context.prec, len(amount.as_tuple().digits) + len(rate.as_tuple().digits))
    return amount * rate
```

Por exemplo, USD `100.00` com taxa `5.420000` vira BRL `542.00`. O valor da reserva já é um total; não deve ser multiplicado novamente pela quantidade de quartos.

Os valores convertidos entram nas somas sem `quantize()`. O relatório dimensiona um contexto decimal local também para a agregação e para a média. Isso evita depender apenas dos 28 dígitos de precisão padrão.

O arredondamento para duas casas acontece em `format_money()`, usando `ROUND_HALF_UP`, quando os campos de saída são montados. A média usa o total exato dividido pelas noites, antes de formatar qualquer um dos dois campos.

Um exemplo coberto pelos testes: três reservas de USD `0.01`, com taxa `5.42`, somam `0.1626` e saem como `"0.16"`. Arredondar cada reserva antes da soma produziria `"0.15"`.

## 5. Tratamento dos status

### Prompt

> Olha como os status estão sendo tratados. Todas as reservas precisam entrar na contagem, mas só as confirmadas podem entrar nos valores e nas noites. Quero conferir se isso vale também pros meses e pros hotéis.

### Resposta

A política original era:

```python
return status != "CANCELLED"
```

Isso também aceita `NO_SHOW`, que não é faturável. A regra correta, presente na versão atual, é:

```python
return status == "CONFIRMED"
```

No `ReportBuilder`, todas as linhas são lidas e convertidas antes do filtro. A contagem de status percorre essa lista completa, então canceladas e no-show continuam aparecendo em `total_reservations` e nas suas contagens individuais.

Somente depois são criadas as entradas faturáveis. O mesmo conjunto filtrado alimenta noites, total financeiro, média, meses e hotéis. Assim, uma reserva não faturável também não cria um mês ou hotel vazio nos grupos.

Há um teste com apenas uma cancelada e uma no-show: são duas reservas no resumo, valores e noites ficam zerados, e `by_month` e `top_hotels` ficam vazios. Outro teste garante que uma linha cancelada com campo numérico inválido seja rejeitada no parsing, em vez de escapar da validação pelo filtro de status.

## 6. Ranking e agrupamento por mês

### Prompt

> Confere o ranking dos hotéis e o agrupamento por mês. O ranking precisa trazer os maiores valores primeiro e desempatar pelo ID. Já o mês tem que ser o do check-in, mesmo quando a estadia termina no mês seguinte.

### Resposta

O ranking original ordenava pelo valor crescente. A chave atual resolve as duas condições do enunciado:

```python
ranked_hotels = sorted(
    hotels.items(),
    key=lambda item: (-item[1]["amount"], item[0]),
)
```

O sinal negativo coloca os maiores totais primeiro. Se os valores exatos forem iguais, o ID fica em ordem crescente. Depois da ordenação, o resultado é limitado a `--top`; se houver menos hotéis, todos são retornados.

A comparação usa os valores exatos antes da serialização. Se H01 tiver `1.001` e H02 tiver `1.002`, H02 vem primeiro, embora ambos apareçam como `"1.00"` no JSON. O empate por ID só se aplica quando os totais realmente são iguais.

Para os meses, a versão atual usa:

```python
month_key = row.checkin.isoformat()[:7]
```

Uma reserva de 31/12 a 02/01 entra integralmente em dezembro, com suas duas noites; o contrato não divide a estadia entre os meses. Os grupos são apresentados por chave de mês crescente. O uso de ISO também mantém quatro dígitos no ano para datas anteriores ao ano 1000.

## 7. Testes adicionais

### Prompt

> Me ajuda a montar uns testes além dos que já vieram. Quero pegar casos que podem passar despercebidos, tipo arquivo vazio, mais de 200 reservas, empate entre hotéis e valores que dão fração de centavo. Explica o que cada teste vai garantir.

### Resposta

Os cinco testes fornecidos devem continuar inalterados. Os testes adicionais existentes estão separados em `test_report_edges.py`, `test_cli_contract.py` e `test_report_reference.py`.

Os principais casos são:

| Caso | O que garante |
| --- | --- |
| CSV com cabeçalho e nenhuma reserva | Resumo zerado, média `"0.00"` e grupos vazios. Um arquivo sem cabeçalho obrigatório continua inválido. |
| 201 reservas | O leitor processa além do antigo limite de 200, refletindo a última linha nas contagens e nos totais. |
| Apenas canceladas e no-show | Todas entram nas contagens, mas nenhuma entra nos agregados. |
| Virada de mês/ano, ano bissexto e vários quartos | A diferença considera o calendário e multiplica a estadia pelos quartos. |
| Três valores convertidos de `0.0542` | A soma exata é arredondada no final para `"0.16"`. |
| Total `0.005` e duas noites de quarto | O total sai `"0.01"`, mas a média usa `0.0025` e sai `"0.00"`. |
| Valor `9007199254740993.01` | O dinheiro não perde precisão ao passar por `float`. |
| Hotéis com totais iguais | O desempate respeita o ID crescente. |
| Totais diferentes que aparecem iguais após arredondar | O ranking usa o total exato. |
| Amostra oficial e dataset de 300 reservas | Os agregados completos continuam compatíveis com as referências. |
| CLI executado em subprocesso | Argumentos, arquivos de saída, stdout, stderr e códigos `0`, `1` e `2` funcionam no processo real. |

Os testes de referência calculam os relatórios separadamente com `Fraction`, sem reutilizar as funções financeiras de produção. Também há conjuntos gerados com sementes fixas e cenários com escalas decimais maiores. Isso ajuda a encontrar diferenças que não aparecem nos exemplos pequenos.

## 8. Revisão das alterações

### Prompt

> Faz uma revisão das alterações e procura alguma coisa que ainda possa dar resultado errado. Se encontrar um problema, monta primeiro um teste que reproduza ele, depois mostra a correção e roda os testes de novo.

### Resposta

Uma revisão além dos exemplos oficiais precisa olhar para a precisão do próprio `Decimal` e para a classificação dos erros de arquivo.

Usar `Decimal` resolve a representação dos valores, mas as operações ainda obedecem a um contexto de precisão. Com o padrão de 28 dígitos, somar um valor muito grande com meio centavo pode perder a parcela pequena antes da serialização. Valores muito próximos de meio centavo também podem ser arredondados cedo demais.

Os testes atuais reproduzem esses limites com valores de mais de 28 dígitos, soma de um valor grande com `0.005` e médias ao redor de meio centavo. A referência com frações permite conferir o resultado sem compartilhar o mesmo limite decimal.

A correção presente no código usa `localcontext()`: a multiplicação reserva dígitos para os dois coeficientes; a agregação considera as casas inteiras, a menor escala, o número de parcelas e o divisor da média. O contexto externo de quem chama o código permanece preservado.

Outro caso coberto é uma entrada que seja um link simbólico em ciclo. Ela deve terminar como entrada inválida, código `2`. A versão atual usa `samefile()` na proteção contra sobrescrever os arquivos de entrada e deixa o repositório classificar a falha de leitura. Há testes tanto para o ciclo quanto para aliases por links simbólicos e físicos.

Os testes de reprodução identificaram os defeitos de precisão decimal e de links em ciclo antes das correções. Após os ajustes, a suíte foi executada novamente. O projeto original apresentou cinco falhas; a versão corrigida apresentou os seguintes resultados:

```text
139 passed
All checks passed!
24 files already formatted
```

Os testes passaram após as correções, assim como as verificações de lint e formatação.

## 9. Revisão do README

### Prompt

> Revisa o README e tenta executar os comandos que estão nele. Quero conferir se outra pessoa consegue rodar o projeto e se a documentação bate com o que foi implementado.

### Resposta

Os comandos de execução documentados correspondem à interface atual: `--input` e `--rates` são obrigatórios; `--output` tem padrão `output/report.json`; `--top` tem padrão `5` e aceita inteiro maior ou igual a um. O pacote roda com `PYTHONPATH=src`, e o CLI usa somente a biblioteca padrão.

As dependências de desenvolvimento estão fixadas em `requirements-dev.txt`. O ambiente virtual existente permite executar:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Nesta revisão, os três comandos passaram, com 139 testes aprovados. Os dois comandos do CLI também foram executados usando os CSVs fornecidos e arquivos de saída temporários em `/tmp`, com estes resumos:

```text
Reservas: 12 | Confirmadas: 9 | Noites: 28 | Total BRL: 7566.00
Reservas: 300 | Confirmadas: 235 | Noites: 1347 | Total BRL: 396170.00
```

Os resultados correspondem às tabelas do README. Os testes também conferem as médias `270.21` e `294.11`, os meses, o ranking, os tipos dos campos e o offset fixo `-03:00`.

O README de entrega descreve as causas dos defeitos, a abordagem de investigação e os comandos de validação. A configuração de CI repete testes, lint e formatação, mas a existência do workflow não comprova uma execução remota bem-sucedida.

Não foi feita uma instalação limpa das dependências nesta revisão; foi usado o ambiente já existente. Os prompts e as respostas da assistência de IA estão registrados neste log.
