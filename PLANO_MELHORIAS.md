# Plano de melhorias e novas funcionalidades

Este documento descreve um roteiro prático para evoluir o aplicativo PGN To HTML 2. A ordem abaixo prioriza primeiro estabilidade e organização, depois recursos novos.

## 1. Preparação do projeto

### Objetivo

Deixar o projeto mais fácil de instalar, executar, testar e versionar.

### Passos

1. Criar um `.gitignore` na raiz.
   - Ignorar `__pycache__/`, `*.pyc`, ambientes virtuais, saídas geradas e arquivos temporários.
   - Avaliar se `PGN/Diagrams/` deve ficar fora do repositório, pois contém muitos artefatos gerados.

2. Criar `requirements.txt`.
   - Incluir dependências principais:
     - `python-chess`
     - `PySide6`
     - `ebooklib`
     - `python-docx`
     - `cairosvg`
     - `Pillow`
     - `fonttools`

3. Criar `README.md`.
   - Explicar o que o aplicativo faz.
   - Explicar como instalar dependências.
   - Explicar como executar.
   - Explicar como rodar testes.

4. Configurar descoberta de testes.
   - Opção simples: manter `unittest` e documentar:

   ```powershell
   python -m unittest discover -s tests -v
   ```

   - Opção melhor: adicionar um `pytest.ini` e migrar gradualmente para `pytest`.

### Critério de aceite

- Um novo usuário consegue instalar, executar e testar o projeto seguindo o `README.md`.
- O comando de testes roda de forma clara e documentada.

## 2. Corrigir contrato do estilo Merida

### Objetivo

Eliminar a falha atual dos testes e deixar claro se `diagram_style` retorna o alias original ou o estilo normalizado.

### Situação atual

Ao chamar:

```python
convert_pgn(pgn, diagram_style="merida")
```

o resultado retorna:

```python
result.diagram_style == "font:chessmerida.ttf"
```

mas o teste espera:

```python
result.diagram_style == "merida"
```

### Passos

1. Decidir o contrato público.
   - Recomendado: `ConversionResult.diagram_style` deve guardar o estilo normalizado.
   - Motivo: internamente agora há suporte a múltiplas fontes, não só Merida.

2. Atualizar o teste em `tests/test_conversion.py`.
   - Trocar a expectativa literal `"merida"` por uma verificação de estilo de fonte.
   - Exemplo:

   ```python
   self.assertTrue(chess_diagrams.uses_merida_style(result.diagram_style))
   ```

3. Adicionar teste específico para alias.
   - Verificar que `"merida"`, `"chessmerida"` e `"font:chessmerida.ttf"` resolvem para um estilo válido quando a fonte existe.

### Critério de aceite

- `python -m unittest discover -s tests -v` passa sem falhas.
- O comportamento de `diagram_style` está documentado.

## 3. Substituir divisão de PGN por parser sequencial

### Objetivo

Evitar falhas em PGNs que não começam com `[Event]`, têm tags em ordem diferente ou contêm texto antes da primeira partida.

### Arquivo principal

- `PGN_To_HTML_2/PGN_para_Livro_PERFEITO8.py`

### Situação atual

`convert_pgn` usa:

```python
re.split(r'(?=\[Event\s)', pgn_text.strip())
```

Isso é frágil.

### Passos

1. Criar função nova:

```python
def iter_pgn_games(pgn_text):
    pgn_io = io.StringIO(pgn_text)
    while True:
        game = chess.pgn.read_game(pgn_io)
        if game is None:
            break
        yield game
```

2. Adaptar `convert_pgn`.
   - Em vez de iterar `raw_games`, iterar objetos `game`.
   - Para fallback, preservar o texto bruto da partida é mais difícil. Existem duas opções:
     - opção simples: usar fallback apenas quando `read_game` retorna jogo com erros;
     - opção completa: criar antes um extrator de blocos PGN bruto mais robusto.

3. Ler `game.errors`.
   - Se houver erros, adicionar avisos em `ConversionResult.warnings`.
   - Exemplo:

   ```python
   if getattr(game, "errors", None):
       result.warnings.append(f"Partida {count}: {len(game.errors)} erro(s) de PGN.")
   ```

4. Manter fallback para casos realmente ilegíveis.
   - Se ainda quiser compatibilidade textual, criar função separada `split_pgn_text_blocks`.
   - Essa função não deve depender apenas de `[Event]`; deve reconhecer qualquer tag inicial.

### Testes

Adicionar casos:

1. PGN começando com `[White "..."]` sem `[Event]`.
2. PGN com tags em ordem incomum.
3. PGN com texto introdutório antes da primeira partida.
4. PGN com duas partidas válidas.
5. PGN com uma partida inválida que gera aviso.

### Critério de aceite

- Conversão funciona para PGNs válidos mesmo sem `[Event]`.
- Erros do `python-chess` aparecem como avisos.
- Testes cobrem múltiplas partidas.

## 4. Separar a arquitetura em módulos menores

### Objetivo

Reduzir o tamanho e o acoplamento de `PGN_para_Livro_PERFEITO8.py`.

### Estrutura sugerida

```text
PGN_To_HTML_2/
  __init__.py
  app.py
  converter.py
  models.py
  html_export.py
  docx_export.py
  epub_export.py
  chess_diagrams.py
  pgn_qt_window.py
  legacy_tk.py
```

### Responsabilidades

`models.py`

- `DiagramAsset`
- `ConversionResult`

`converter.py`

- `convert_pgn`
- `GameHtmlBuilder`
- fallback parser
- NAG map
- helpers de cabeçalho e comentários

`html_export.py`

- CSS base
- `build_css`
- `ensure_diagram_font_css`
- `gerar_html_final`
- `write_html_bundle`

`docx_export.py`

- `DocxBlockParser`
- `write_docx_file`

`epub_export.py`

- criação de EPUB
- cópia de assets
- empacotamento de fontes

`app.py`

- ponto de entrada
- importa Qt app e backend

### Passos

1. Criar `models.py` e mover dataclasses.
2. Mover funções HTML sem alterar comportamento.
3. Mover DOCX para `docx_export.py`.
4. Mover EPUB para `epub_export.py`.
5. Ajustar imports.
6. Rodar testes a cada etapa.
7. Manter `PGN_para_Livro_PERFEITO8.py` como camada de compatibilidade por um tempo:

```python
from converter import convert_pgn, processar_pgn_worker
from html_export import gerar_html_final, write_html_bundle
from docx_export import write_docx_file
```

### Critério de aceite

- Todos os testes passam após cada extração.
- A UI continua abrindo.
- Scripts antigos que importam `PGN_para_Livro_PERFEITO8.py` continuam funcionando.

## 5. Remover ou arquivar `diagramas.py`

Status: concluido. A versao antiga foi movida para `archive/diagramas_legacy.py`.

### Objetivo

Eliminar duplicação da versão antiga em Tkinter baseada em regex.

### Passos

1. Confirmar se `diagramas.py` ainda é usado.
2. Se não for usado, mover para:

```text
archive/diagramas_legacy.py
```

3. Adicionar aviso no topo do arquivo arquivado:

```python
"""Versão legada. Mantida apenas para referência histórica."""
```

4. Garantir que o app principal usa somente a UI Qt.

### Critério de aceite

- Não há duas implementações ativas de parser/exportador.
- O usuário não fica em dúvida sobre qual arquivo executar.

## 6. Diagramas ao longo da partida

Status: concluido para a linha principal. Marcadores `{#diagram}` e `{[%diagram]}` geram diagramas na posicao apos o lance e sao removidos do comentario visivel.

### Objetivo

Permitir inserir diagramas depois de lances específicos, não apenas na posição inicial por FEN.

### Sintaxes sugeridas

Suportar comentários PGN:

```pgn
12. Nf6+ {#diagram}
```

ou:

```pgn
12. Nf6+ {[%diagram]}
```

### Passos

1. Criar função:

```python
def comment_requests_diagram(comment):
    return "#diagram" in comment or "[%diagram]" in comment
```

2. Em `GameHtmlBuilder.process_game`, após aplicar o lance e detectar comentário, verificar se o comentário pede diagrama.

3. Gerar FEN da posição atual.
   - Depois do lance, usar:

   ```python
   board_after = next_node.board()
   fen = board_after.fen()
   ```

4. Gerar diagrama com nome único:

```python
base_name=f"diagram_partida_{idx}_move_{move_number}"
```

5. Remover o marcador `#diagram` do comentário visível.

6. Adicionar o asset em `ConversionResult.diagram_assets`.

### Testes

1. PGN com `{#diagram}` gera imagem.
2. Comentário exportado não mostra `#diagram`.
3. HTML contém `<div class="diagram">`.
4. EPUB e DOCX incluem o diagrama.

### Critério de aceite

- Usuário consegue marcar posições no PGN.
- HTML, EPUB e DOCX respeitam os diagramas intermediários.

## 7. Sumário do livro

Status: concluido para HTML, EPUB e DOCX. O resultado da conversao agora inclui `summaries`, cada partida recebe `id="game-N"` e o HTML final insere um sumario navegavel.

### Objetivo

Criar índice navegável no HTML/EPUB/DOCX.

### Passos

1. Criar modelo `GameSummary`.

```python
@dataclass
class GameSummary:
    index: int
    white: str
    black: str
    event: str
    site: str
    date: str
    eco: str
    result: str
    anchor: str
```

2. Adicionar `summaries` em `ConversionResult`.

3. Ao montar cada partida, gerar anchor:

```html
<section id="game-1" class="game">
```

4. Criar função:

```python
def build_toc_html(summaries):
    ...
```

5. Incluir sumário no início de `gerar_html_final`.

6. Para EPUB, usar `book.toc` com títulos reais:

```text
1. White - Black [ECO]
```

7. Para DOCX, inserir uma seção inicial com lista numerada.

### Testes

- HTML contém links `#game-1`, `#game-2`.
- EPUB tem capítulos com nomes das partidas.
- DOCX contém seção "Sumário".

### Critério de aceite

- Livros grandes ficam navegáveis.

## 8. Filtros e seleção de partidas

Status: concluido. Foram adicionados `scan_pgn_headers`, `filter_game_summaries`, suporte a `selected_game_indexes` em `convert_pgn` e diálogos de seleção/filtro nas interfaces Qt e legada.

### Objetivo

Permitir converter apenas parte do PGN.

### Recursos

- Filtrar por jogador.
- Filtrar por ECO.
- Filtrar por resultado.
- Filtrar por intervalo de partidas.
- Selecionar/desmarcar partidas manualmente.

### Passos

1. Criar fase de leitura de metadados sem converter tudo.

```python
def scan_pgn_headers(pgn_text) -> list[GameSummary]:
    ...
```

2. Na UI Qt, adicionar aba "Partidas".
   - Tabela com colunas:
     - incluir
     - número
     - brancas
     - pretas
     - ECO
     - resultado
     - evento

3. Adicionar filtros acima da tabela.

4. Alterar `convert_pgn` para aceitar:

```python
selected_game_indexes=None
```

5. Converter apenas os índices selecionados.

### Testes

- Converter somente partida 2 de 3.
- Filtro por ECO retorna partidas corretas.
- Filtro por jogador funciona com brancas e pretas.

### Critério de aceite

- Usuário controla o conteúdo exportado antes de gerar o livro.

## 9. Presets de CSS

Status: concluido. Foram adicionados presets `classic`, `modern`, `print-a4`, `ereader` e `tactics`, com seletor de tema na UI Qt e na UI legada.

### Objetivo

Oferecer estilos prontos sem obrigar o usuário a editar CSS manualmente.

### Presets sugeridos

1. Clássico livro.
2. Moderno limpo.
3. Impressão A4.
4. E-reader.
5. Estudo tático.

### Passos

1. Criar pasta:

```text
PGN_To_HTML_2/styles/
```

2. Criar arquivos:

```text
classic.css
modern.css
print-a4.css
ereader.css
tactics.css
```

3. Criar função:

```python
def load_css_preset(name, diagram_style):
    ...
```

4. Na UI, adicionar combo "Tema".

5. Ao trocar tema, atualizar editor CSS e preview.

6. Garantir que CSS de fonte Merida seja anexado automaticamente.

### Testes

- Cada preset gera CSS não vazio.
- Cada preset mantém regras de diagrama.
- Merida continua incluindo `@font-face`.

### Critério de aceite

- Usuário pode trocar visual sem editar CSS.

## 10. Exportação PDF

Status: concluido. Foi criado `pdf_export.py`, com `write_pdf_file`, suporte opcional a Playwright/Chromium e botão `Salvar PDF` nas interfaces Qt e legada.

### Objetivo

Gerar PDF paginado a partir do HTML.

### Opções técnicas

Opção A: Playwright

- Melhor fidelidade visual.
- Usa Chromium headless.

Opção B: WeasyPrint

- Bom para HTML/CSS de impressão.
- Pode exigir dependências nativas.

### Recomendação

Usar Playwright primeiro, por ser mais próximo do preview em navegador.

### Passos

1. Adicionar dependência opcional:

```powershell
pip install playwright
python -m playwright install chromium
```

2. Criar `pdf_export.py`.

3. Implementar:

```python
def write_pdf_file(pdf_path, conversion_result, css_text=None):
    ...
```

4. Gerar HTML temporário com assets.

5. Usar Chromium headless:

```python
page.pdf(path=pdf_path, format="A4", print_background=True)
```

6. Adicionar botão "Salvar PDF" na UI.

7. Adicionar CSS `@media print`.

### Testes

- PDF é criado.
- PDF não fica vazio.
- Diagramas aparecem.

### Critério de aceite

- Usuário consegue exportar PDF diretamente pela UI.

## 11. Validador de PGN

Status: concluido. Foi criado `pgn_validation.py`, com `validate_pgn`, `format_validation_report`, modelo `PgnValidationIssue` e botão `Validar PGN` nas interfaces Qt e legada.

### Objetivo

Mostrar problemas antes da conversão.

### Passos

1. Criar função:

```python
def validate_pgn(pgn_text) -> list[PgnValidationIssue]:
    ...
```

2. Modelo:

```python
@dataclass
class PgnValidationIssue:
    game_index: int
    severity: str
    message: str
    context: str
```

3. Usar `game.errors` do `python-chess`.

4. Na UI, adicionar botão "Validar PGN".

5. Mostrar relatório em painel ou janela:
   - partida
   - severidade
   - mensagem
   - ação sugerida

6. Permitir "converter mesmo assim".

### Testes

- PGN válido retorna lista vazia.
- Lance ilegal retorna erro.
- PGN com tag faltante retorna aviso.

### Critério de aceite

- Usuário entende problemas antes de exportar.

## 12. Cache de diagramas

Status: concluido. Diagramas clássicos agora usam hash de FEN, estilo e tamanho; posições iguais reutilizam SVG/PNG. Foi adicionada função `clear_diagram_cache` e botão `Limpar Cache` nas interfaces.

### Objetivo

Evitar recriar diagramas idênticos e reduzir arquivos duplicados.

### Passos

1. Criar função:

```python
def diagram_cache_key(fen, style, size):
    ...
```

2. Gerar hash curto:

```python
hashlib.sha1(f"{fen}|{style}|{size}".encode()).hexdigest()[:12]
```

3. Nomear arquivos:

```text
diagram_<hash>.svg
diagram_<hash>.png
```

4. Antes de gerar, verificar se arquivos existem.

5. Adicionar opção para limpar cache.

### Testes

- Dois diagramas com mesma FEN usam mesmo arquivo.
- FEN diferente gera arquivo diferente.
- Estilo diferente gera arquivo diferente.

### Critério de aceite

- Conversões grandes ficam mais rápidas e geram menos arquivos.

## 13. Integração com Stockfish

Status: concluido na UI Qt e no backend. Foi criado `engine_analysis.py`, o conversor aceita análise opcional com Stockfish, renderiza avaliações discretas no HTML e mantém a conversão normal quando o motor não está configurado ou falha.

### Objetivo

Adicionar análise opcional de motor.

### Recursos possíveis

- Avaliação por lance.
- Melhor lance sugerido.
- Marcação de erros.
- Gráfico de avaliação.
- Criação de exercícios táticos.

### Passos

1. Criar configuração de caminho do Stockfish.
   - Campo na UI.
   - Salvar em arquivo local de preferências.

2. Criar módulo `engine_analysis.py`.

3. Implementar:

```python
def analyze_game(game, engine_path, depth=12):
    ...
```

4. Usar `chess.engine.SimpleEngine.popen_uci`.

5. Retornar lista:

```python
@dataclass
class MoveAnalysis:
    ply: int
    san: str
    fen: str
    score_cp: int | None
    mate: int | None
    best_move: str
```

6. Integrar no HTML.
   - Mostrar avaliação discreta ao lado do lance.
   - Opcionalmente gerar gráfico.

7. Adicionar limites.
   - Profundidade configurável.
   - Botão cancelar.
   - Processamento em thread.

### Testes

- Testes unitários devem mockar o motor.
- Teste manual com Stockfish real.

### Critério de aceite

- Análise é opcional.
- Conversão normal não depende de Stockfish.
- Erros de motor não quebram exportação.

## 14. Modo livro de exercícios

Status: concluido. O conversor reconhece marcadores `#exercise` e `[%exercise "..."]`, gera blocos HTML de exercícios com diagrama, pergunta e solução sugerida, e a UI permite escolher entre `Livro completo`, `Somente exercícios` e `Livro + exercícios`.

### Objetivo

Transformar posições marcadas em exercícios.

### Sintaxe sugerida

```pgn
12. Nf6+ {#exercise Encontre o melhor lance}
```

ou:

```pgn
12. Nf6+ {[%exercise "Brancas jogam e ganham"]}
```

### Passos

1. Criar detector:

```python
def parse_exercise_marker(comment):
    ...
```

2. Ao encontrar marcador, gerar bloco:

```html
<section class="exercise">
  <h3>Exercício 1</h3>
  <div class="diagram">...</div>
  <p class="question">...</p>
  <details>
    <summary>Solução</summary>
    ...
  </details>
</section>
```

3. Para DOCX, renderizar como:
   - título do exercício
   - diagrama
   - pergunta
   - solução em parágrafo separado

4. Para EPUB, manter `<details>` se compatível, ou usar solução logo abaixo.

5. Adicionar modo na UI:
   - "Livro completo"
   - "Somente exercícios"
   - "Livro + exercícios"

### Testes

- Marcador gera exercício.
- Solução não aparece no comentário normal.
- Exportações incluem exercício.

### Critério de aceite

- Usuário consegue criar material de treino a partir do PGN.

## 15. Melhorias no preview

Status: concluido na UI Qt. O HTML Viewer agora tem navegação por partida, modos `Normal`, `A4` e `E-reader`, controle de zoom, preview parcial para documentos grandes e botão `Documento completo`.

### Objetivo

Tornar o preview mais útil para livros grandes.

### Recursos

- Zoom.
- Modo página A4.
- Modo e-reader.
- Navegação por partida.
- Sincronização HTML-preview mais clara.

### Passos

1. Adicionar controle de zoom no `pgn_qt_window.py`.
   - Usar `QWebEngineView.setZoomFactor`.

2. Adicionar combo de modo de visualização.
   - Normal.
   - Impressão A4.
   - E-reader.

3. Criar painel lateral de partidas usando `ConversionResult.summaries`.

4. Ao clicar numa partida, rolar preview até `#game-N`.

5. Melhorar preview parcial de documentos grandes.
   - Mostrar claramente qual partida está carregada.
   - Botão "carregar documento completo".

### Critério de aceite

- Usuário consegue navegar livros grandes sem depender só do HTML bruto.

## 16. Ordem recomendada de implementação

1. Preparação do projeto.
2. Correção do teste Merida.
3. Parser sequencial com `python-chess`.
4. Separação em módulos.
5. Arquivar `diagramas.py`.
6. Diagramas intermediários.
7. Sumário.
8. Presets de CSS.
9. Validador de PGN.
10. Filtros de partidas.
11. Cache de diagramas.
12. Exportação PDF.
13. Melhorias no preview.
14. Modo exercícios.
15. Integração Stockfish.

## 17. Checklist de qualidade por etapa

Status: concluido para o ciclo atual. A suite automatizada foi ampliada para 30 testes, cobrindo conversão, diagramas, cache, validação, seleção de partidas, PDF, exercícios e análise Stockfish mockada.

Antes de concluir cada fase:

1. Rodar testes:

```powershell
python -m unittest discover -s tests -v
```

2. Testar manualmente:
   - abrir PGN
   - processar
   - preview
   - salvar HTML
   - salvar EPUB
   - salvar DOCX

3. Testar pelo menos:
   - PGN simples sem FEN
   - PGN com FEN inicial
   - PGN com variantes
   - PGN com comentários
   - PGN com NAGs
   - PGN com várias partidas

4. Confirmar que assets são copiados corretamente:
   - `style.css`
   - `Diagrams/*.svg`
   - `Diagrams/*.png`
   - `Fonts/*.ttf` quando necessário

5. Conferir se o app não trava a UI durante processamento pesado.

## 18. Riscos principais

Status: concluido. As mitigações foram registradas no código e na documentação: análise Stockfish opcional com cancelamento cooperativo, dependências separadas entre básicas e opcionais, exportadores cobertos por testes e documentação deixando claro o limite do DOCX.

1. Refatoração grande quebrar exportadores.
   - Mitigação: mover um módulo por vez e rodar testes sempre.

2. EPUB ser mais restrito que HTML normal.
   - Mitigação: manter HTML de EPUB simples e testado.

3. DOCX não preservar todos os estilos.
   - Mitigação: aceitar que DOCX é uma renderização própria, não cópia perfeita do HTML.

4. Stockfish deixar o app lento.
   - Mitigação: análise opcional, com cancelamento e profundidade configurável.

5. Muitas dependências opcionais confundirem instalação.
   - Mitigação: separar dependências básicas e extras.

## 19. Meta final

Status: concluido. O ciclo de melhorias entregou parser robusto, refatoração em módulos, exportações HTML/EPUB/DOCX/PDF, temas, sumário, filtros, validação, cache de diagramas, preview avançado, exercícios e análise opcional com Stockfish.

Ao final, o aplicativo deve ser:

- mais confiável para PGNs variados;
- mais fácil de manter;
- capaz de exportar HTML, EPUB, DOCX e PDF;
- capaz de gerar diagramas iniciais e intermediários;
- navegável por sumário;
- customizável por temas;
- preparado para análise de motor e criação de exercícios.
