# Sistema Legacy

Sistema de gestão para a operação da Legacy 3D Studio, reconstruído do zero com Flask + PostgreSQL.

## V1 funcional

- Primeiro acesso com criação de administrador
- Dashboard operacional
- Clientes
- Estoque de filamentos com histórico de movimentações
- Máquinas
- Orçamentos em USD ou BRL
- Fluxo: preparação → aguardando aprovação → aprovado → execução → impressão → concluído → entregue
- Baixa automática de filamento somente ao entrar em impressão
- Ajuste pelo consumo real ao concluir
- Projetos de clientes e Projetos Legacy
- Upload e armazenamento de STL/arquivos no PostgreSQL (limite atual 15 MB por arquivo)
- Catálogo de produtos Legacy e estoque de produtos prontos
- Catálogo público em `/catalog`

## Deploy no Render

O arquivo `render.yaml` cria um Web Service `sistema-legacy` e um PostgreSQL `sistema-legacy-db`.

Depois do primeiro deploy, abra a aplicação. Como o banco estará vazio, o sistema redirecionará automaticamente para `/setup`, onde você cria o primeiro administrador.

> Observação: o plano PostgreSQL Free do Render é adequado para teste e expira conforme as regras atuais do Render. Para operação real/produção, migre o banco para uma instância persistente paga antes de depender dele como banco definitivo.
