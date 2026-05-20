# PGN To HTML 2

Aplicativo para converter arquivos PGN em livros de xadrez com saída em HTML, EPUB, DOCX e PDF. O projeto usa `python-chess` para ler partidas, gera diagramas em SVG/PNG ou em fonte de xadrez, e inclui uma interface Qt com preview HTML.

## Instalação

Recomendado usar um ambiente virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Para uma instalação mais enxuta, use:

```powershell
python -m pip install -r requirements-base.txt
```

Recursos extras ficam em:

```powershell
python -m pip install -r requirements-optional.txt
python -m playwright install chromium
```

## Execução

```powershell
python PGN_To_HTML_2\PGN_para_Livro_PERFEITO8.py
```

## Marcadores de diagrama

Para inserir um diagrama no meio da partida, adicione um marcador no comentário do lance:

```pgn
12. Nf6+ {#diagram Posição crítica}
```

Também é aceito:

```pgn
12. Nf6+ {[%diagram]}
```

E PGNs que usam a marcação curta também geram diagrama:

```pgn
12. Nf6+ {[#]}
```

O marcador é removido do texto final e o diagrama é gerado na posição após o lance comentado.

Também é possível inserir um diagrama manualmente no HTML já gerado. Posicione o cursor no editor `HTML gerado` e clique em `Gerar Diagrama`; o aplicativo tenta identificar a posição correspondente no PGN e insere o diagrama naquele ponto do HTML.

## Modo exercícios

Para transformar uma posição em exercício, adicione um marcador no comentário do lance:

```pgn
12. Nf6+ {#exercise Encontre o melhor lance}
```

Também é aceito:

```pgn
12. Nf6+ {[%exercise "Brancas jogam e ganham"]}
```

O exercício é criado com a posição após o lance comentado. Quando houver um próximo lance na linha principal, ele é usado como solução sugerida. O marcador é removido do comentário normal.

A interface tem o seletor `Exercícios` com três modos:

- `Livro completo`: gera o livro normal e mantém os exercícios apenas como metadados internos.
- `Somente exercícios`: gera apenas os blocos de exercícios.
- `Livro + exercícios`: gera o livro normal seguido pelos exercícios.

## Análise Stockfish

A interface Qt tem a opção `Análise Stockfish`. Para usar:

1. Baixe o executável do Stockfish para o seu sistema.
2. Marque `Análise Stockfish`.
3. Escolha o caminho do `stockfish.exe`.
4. Ajuste a profundidade.
5. Processe ou exporte normalmente.

Quando ativada, a análise adiciona uma pequena avaliação ao lado de cada lance, com tooltip indicando avaliação e melhor lance sugerido. A análise é opcional: sem caminho de motor, a conversão continua normal. Se o motor falhar, o aplicativo registra um aviso e mantém a exportação.

As preferências locais do motor ficam em `.pgn_to_html_settings.json`, arquivo ignorado pelo Git.

Durante uma análise longa, use `Cancelar` para parar ao fim da etapa atual. A chamada em execução do motor termina antes do cancelamento ser aplicado.

O mesmo arquivo de preferências guarda a última pasta usada para abrir PGN ou salvar HTML, EPUB, DOCX, PDF e CSS.

## Sumário

O HTML final inclui automaticamente um sumário navegável quando o PGN tem uma ou mais partidas. Cada partida recebe um identificador estável, como `game-1`, `game-2`, e o índice usa os metadados do PGN: jogadores, ECO, evento, local, data e resultado.

## Validação de PGN

A interface tem o botão `Validar PGN`, que verifica o texto antes da conversão e mostra:

- erros de parsing do `python-chess`, como lances ilegais;
- tags importantes ausentes, como `White`, `Black` e `Result`;
- partidas sem lances na linha principal;
- texto vazio ou sem partida PGN reconhecível.

A validação não bloqueia a conversão automaticamente; ela informa os problemas para o usuário decidir como prosseguir.

## Seleção e filtros de partidas

O botão `Selecionar Partidas` permite marcar quais partidas serão convertidas. A janela de seleção inclui filtros por:

- jogador;
- ECO;
- resultado.

A seleção é respeitada no processamento para HTML e também nas exportações diretas para EPUB e DOCX. Quando todas as partidas estão marcadas, o aplicativo trata como conversão completa.

## Cache de diagramas

Diagramas clássicos em SVG/PNG usam cache por posição. O nome do arquivo é baseado em hash de FEN, estilo e tamanho, por exemplo `diagram_abc123def456.svg`. Quando a mesma posição aparece novamente, o aplicativo reutiliza o mesmo arquivo.

O botão `Limpar Cache` remove os arquivos cacheados da pasta `Diagrams` associada ao PGN aberto, sem remover nomes antigos como `diagram_partida_1_1.svg`.

## Exportação PDF

O botão `Salvar PDF` converte o livro para PDF usando Playwright/Chromium. Depois de instalar as dependências, execute uma vez:

```powershell
python -m playwright install chromium
```

A exportação PDF respeita a seleção de partidas, o estilo de diagramas e o CSS/tema atual.

## Preview HTML

A aba `HTML Viewer` inclui controles para:

- navegar diretamente para uma partida pelo seletor `Partida`;
- alternar o modo de visualização entre `Normal`, `A4` e `E-reader`;
- ajustar o zoom entre 75% e 200%;
- manter ou desligar atualização automática do preview.

Em documentos grandes, o botão `Atualizar Viewer` carrega uma seção parcial próxima à posição atual do editor HTML. Use `Documento completo` quando quiser carregar o HTML inteiro no viewer.

## Temas CSS

A interface oferece presets de tema no seletor "Tema":

- Clássico
- Moderno limpo
- Impressão A4
- E-reader
- Estudo tático
- Clássico sem fundo
- Moderno limpo sem fundo
- Impressão A4 sem fundo
- E-reader sem fundo
- Estudo tático sem fundo

Os presets ficam em `PGN_To_HTML_2/styles/` e são aplicados sobre o CSS base, mantendo compatibilidade com diagramas clássicos e fontes de xadrez.

## Testes

```powershell
python -m unittest discover -s tests -v
```

## Estrutura atual

- `PGN_To_HTML_2/PGN_para_Livro_PERFEITO8.py`: backend principal e ponto de entrada atual.
- `PGN_To_HTML_2/converter.py`: API preferida para novas integrações de conversão.
- `PGN_To_HTML_2/models.py`: modelos de resultado e assets.
- `PGN_To_HTML_2/html_export.py`: CSS, HTML final e gravação do bundle HTML.
- `PGN_To_HTML_2/pdf_export.py`: exportação PDF via Playwright/Chromium.
- `PGN_To_HTML_2/engine_analysis.py`: análise opcional com Stockfish.
- `PGN_To_HTML_2/pgn_qt_window.py`: interface Qt/PySide6.
- `PGN_To_HTML_2/chess_diagrams.py`: geração de diagramas e suporte a fontes.
- `archive/diagramas_legacy.py`: versão Tkinter legada mantida apenas para referência.
- `tests/`: testes de conversão e exportação.

## Observações

A pasta `PGN/` é tratada como dados locais e não deve ser versionada. Saídas como DOCX, EPUB, PDF e diagramas gerados também ficam fora do Git.
