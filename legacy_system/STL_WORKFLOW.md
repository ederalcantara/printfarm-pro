# Sistema Legacy — fluxo de arquivos STL

## Objetivo

Cada cliente pode ter vários projetos/orçamentos. Cada projeto pode armazenar arquivos STL, imagens e versões técnicas sem depender de uma pasta física específica no servidor.

## Estrutura lógica

Cliente
- Projeto / Orçamento
  - Arquivos STL
  - Imagens de referência
  - Versões
  - Parâmetros de impressão
  - Histórico de produção

## Regras para STL

O arquivo STL fica associado a um projeto/orçamento e a um cliente.

Para cada STL o sistema deve registrar:
- nome original do arquivo;
- nome interno/ID único;
- versão (`v1`, `v2`, `final`, etc.);
- tamanho do arquivo;
- data de upload;
- observações;
- dimensões desejadas X/Y/Z em mm;
- material/filamento escolhido;
- peso estimado pelo slicer em gramas;
- tempo estimado de impressão;
- parâmetros técnicos principais;
- status da versão (`draft`, `approved`, `superseded`).

## Baixa de estoque

O STL sozinho não determina o consumo real de filamento.

O peso estimado deve vir do fatiamento/slicer ou ser informado pelo operador. Quando o projeto entra em `printing`, o sistema baixa automaticamente o peso estimado do estoque uma única vez.

Na conclusão, o operador pode informar o peso real utilizado. O sistema ajusta a diferença:
- peso real menor que o estimado: devolve a diferença ao estoque;
- peso real maior que o estimado: baixa a diferença adicional;
- peso real igual: não faz ajuste.

Toda alteração gera registro no histórico de estoque.

## Armazenamento de arquivos

Os metadados ficam no PostgreSQL. Os arquivos STL não devem ser armazenados dentro do PostgreSQL.

Em produção, os arquivos devem ficar em armazenamento persistente de objetos/arquivos e o banco guarda apenas a referência ao arquivo (URL/chave/caminho lógico), checksum e metadados.

## Segurança e integridade

- usar ID único para cada arquivo;
- manter checksum SHA-256 para detectar arquivo duplicado ou alterado;
- nunca sobrescrever uma versão antiga silenciosamente;
- permitir marcar versão anterior como substituída;
- apagar arquivo somente com confirmação e mantendo registro de auditoria;
- validar extensão e tamanho de upload.

## Evolução futura

Depois da primeira versão, o Sistema Legacy pode integrar um slicer para obter automaticamente:
- peso estimado;
- tempo estimado;
- quantidade de material;
- parâmetros de fatiamento;
- eventualmente G-code associado ao trabalho.
