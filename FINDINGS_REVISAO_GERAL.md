# Findings da Revisao Geral

Data: 2026-05-20

## 1. Alto - Temas podem falhar no executavel empacotado

Status: implementado. `html_export.py` agora busca temas em layouts normais e em `sys._MEIPASS`, incluindo `PGN_To_HTML_2/styles`; `chess_diagrams.py` faz o mesmo para fontes em `Fonts`. Foram adicionados testes simulando o layout PyInstaller.

Arquivos relacionados:

- `PGN_To_HTML_2/html_export.py`
- `PGN_To_HTML_2/chess_diagrams.py`
- build PyInstaller `PGN_To_HTML_2_TESTE.exe`

Problema:

`html_export.py` carrega os temas usando `os.path.dirname(__file__)/styles`. No build onefile do PyInstaller, os estilos foram incluidos como `PGN_To_HTML_2/styles`, enquanto os modulos podem ser importados como top-level. Isso pode fazer o executavel nao encontrar os arquivos CSS ao escolher temas diferentes do classico.

Recomendacao:

Criar um helper de caminho para recursos compatível com `sys._MEIPASS`, ou ajustar o empacotamento para incluir os estilos tambem como `styles;styles`.

## 2. Medio - Preferencias locais podem nao persistir corretamente no executavel

Status: implementado. As preferencias agora usam `app_settings.py`, salvando em uma pasta estavel do usuario (`%APPDATA%/PGN_To_HTML_2` no Windows, com fallback para `XDG_CONFIG_HOME` ou `~/.config`). O app ainda tenta ler o arquivo antigo do projeto quando o novo arquivo nao existe.

Arquivos relacionados:

- `PGN_To_HTML_2/pgn_qt_window.py`
- `PGN_To_HTML_2/PGN_para_Livro_PERFEITO8.py`

Problema:

As preferencias locais usam `project_dir` calculado a partir de `__file__`. Em executavel PyInstaller onefile, esse caminho pode apontar para a pasta temporaria de extracao, nao para uma pasta estavel do usuario. Isso pode fazer `.pgn_to_html_settings.json` ser perdido entre execucoes.

Recomendacao:

Salvar preferencias em uma pasta estavel, por exemplo `%APPDATA%/PGN_To_HTML_2/`, ou ao lado do executavel usando `sys.executable`.

## 3. Medio - Exportacao EPUB nao respeita CSS selecionado ou customizado

Status: implementado. A exportacao EPUB no Qt e no Tkinter agora usa `get_current_css_text()`, preservando o tema selecionado ou CSS editado pelo usuario. O CSS tambem passa por `ensure_diagram_font_css(...)` para manter os recursos de fonte de diagramas quando necessario.

Arquivos relacionados:

- `PGN_To_HTML_2/pgn_qt_window.py`
- `PGN_To_HTML_2/PGN_para_Livro_PERFEITO8.py`

Problema:

A exportacao EPUB usa `build_css(...)` diretamente. Com isso, o EPUB pode ignorar o CSS atual da interface, incluindo temas selecionados ou CSS editado pelo usuario. HTML e PDF ja conseguem usar o CSS atual em alguns fluxos.

Recomendacao:

Usar `get_current_css_text()` tambem na exportacao EPUB, garantindo que o EPUB reflita o mesmo tema/CSS mostrado no HTML.

## 4. Baixo/Medio - Gerar Diagrama usa a pasta do PGN para imagens manuais

Status: implementado. O botao `Gerar Diagrama` agora grava imagens manuais em uma pasta temporaria controlada pelo app, registra os assets no resultado atual e o salvamento continua copiando os arquivos para `Diagrams` no destino final. O preview tambem reescreve os `src="Diagrams/..."` registrados para data URI, permitindo visualizar diagramas manuais antes de salvar o bundle.

Arquivo relacionado:

- `PGN_To_HTML_2/pgn_qt_window.py`

Problema:

O botao `Gerar Diagrama` cria imagens em `self.pgn_dir/Diagrams`. Depois o asset e registrado e copiado ao salvar, entao o fluxo principal funciona. Mas se o usuario editar/mover/salvar HTML fora do bundle correto, os links podem apontar para uma pasta diferente da esperada.

Recomendacao:

Gerar diagramas manuais em uma pasta temporaria controlada pelo app e materializar/copiar os assets somente no destino final ao salvar.

## 5. Baixo - Alteracao local em `print-a4.css` parece acidental

Arquivo relacionado:

- `PGN_To_HTML_2/styles/print-a4.css`

Problema:

O arquivo aparece modificado no Git local. Pelo diff visto durante a revisao, ele parece ter recebido CSS base completo no topo, possivelmente por salvar/exportar CSS sobre o preset. Essa alteracao nao foi commitada nem enviada ao GitHub.

Recomendacao:

Revisar manualmente o conteudo de `print-a4.css`. Se a alteracao foi acidental, restaurar apenas esse arquivo; se foi intencional, validar o tema e commitar em uma etapa propria.

## Validacao realizada

- `python -m unittest discover -s tests -v`: 34 testes OK.
- Repositorio sincronizado com `origin/main`, exceto a alteracao local em `PGN_To_HTML_2/styles/print-a4.css`.
