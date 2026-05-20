# Changelog

## Atual

- Conversão PGN para HTML, EPUB, DOCX e PDF.
- Parser sequencial com `python-chess`, incluindo suporte a PGNs sem `[Event]` e aviso para erros de parsing.
- Diagramas iniciais, diagramas intermediários por marcador e cache por FEN/estilo/tamanho.
- Temas CSS: clássico, moderno, impressão A4, e-reader e estudo tático.
- Sumário navegável com âncoras por partida.
- Validação de PGN antes da conversão.
- Seleção e filtros de partidas por jogador, ECO e resultado.
- Preview HTML Qt com navegação por partida, zoom, modos de visualização, preview parcial e carregamento completo sob demanda.
- Modo exercícios com marcadores `#exercise` e `[%exercise "..."]`.
- Análise Stockfish opcional, com avaliações por lance, profundidade configurável e cancelamento cooperativo.
- Dependências separadas em instalação base e opcionais.
- Suite automatizada cobrindo conversão, exportadores, cache, validação, exercícios, PDF e Stockfish mockado.
