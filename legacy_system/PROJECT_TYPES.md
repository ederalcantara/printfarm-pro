# Sistema Legacy — Tipos de Projeto

O sistema separa claramente trabalhos de clientes e produtos próprios da Legacy.

## Projeto de Cliente

Origem: pedido específico de um cliente.

Fluxo principal:
1. orçamento;
2. aguardando aprovação;
3. aprovado para execução;
4. preparação técnica;
5. impressão;
6. conclusão;
7. entrega.

O projeto fica ligado ao cliente e ao orçamento. Pode ter STL, imagens, versões e perfis de impressão.

## Projeto Legacy

Origem: ideia criada pela própria equipe para catálogo e venda.

Fluxo principal:
1. ideia;
2. desenvolvimento;
3. protótipo;
4. aprovado;
5. produção;
6. catálogo ativo;
7. arquivado, se necessário.

Não exige cliente nem orçamento.

Cada Projeto Legacy pode ter:
- STL e versões;
- imagens de produto;
- perfis de impressão;
- material padrão;
- custo de fabricação;
- preço USD e BRL;
- SKU;
- quantidade em estoque de produto acabado;
- flags para divulgação no Instagram e Facebook.

## Estoque

Existem dois controles diferentes:

### Matéria-prima
Filamento/material em gramas. É baixado quando uma impressão entra em produção.

### Produto acabado
Quantidade de unidades prontas para venda. Quando um lote de Projeto Legacy é concluído, entram unidades no estoque de produto acabado. Quando ocorre uma venda, sai uma unidade ou a quantidade vendida.

## Arquivos

Arquivos STL, imagens, G-code e documentos pertencem ao projeto, não diretamente ao cliente. Isso permite usar a mesma estrutura tanto em Projetos de Cliente quanto em Projetos Legacy.

Os arquivos devem ficar em armazenamento persistente; o PostgreSQL guarda apenas metadados, chave de armazenamento, versão e checksum.
