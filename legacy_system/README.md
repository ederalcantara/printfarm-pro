# Sistema Legacy v1

Nova aplicação de gestão para a operação de impressão 3D Legacy, construída separadamente do Filamanager antigo.

## O que já está implementado

- Login administrativo.
- Dashboard operacional.
- Cadastro e histórico de clientes.
- Estoque de filamentos em gramas, custo por kg, estoque mínimo e movimentações.
- Cadastro de máquinas.
- Projetos de clientes e Projetos Legacy (produtos próprios da equipe).
- Arquivos STL/3MF/OBJ, imagens e G-code associados ao projeto, com versão e SHA-256.
- Orçamentos em USD ou BRL.
- Itens de orçamento com tamanho X/Y/Z, layer, infill, peso estimado, tempo, máquina e filamento.
- Fluxo: Rascunho → Aguardando aprovação → Execução → Preparação → Imprimindo → Concluído → Entregue.
- Baixa automática do filamento somente ao entrar em `printing`.
- Proteção contra baixa duplicada.
- Bloqueio de impressão quando o estoque não é suficiente.
- Registro do peso real ao final e ajuste da diferença no estoque.
- Fila/Kanban de produção.
- Projetos Legacy transformáveis em produtos de catálogo.
- Estoque separado de produtos acabados para venda.
- Campos de legenda para Instagram e Facebook.
- Layout responsivo para celular e computador.
- PostgreSQL via `DATABASE_URL`.
- Blueprint do Render em `legacy_system/render.yaml`.

## Arquivos STL

Os metadados ficam no PostgreSQL. Para guardar o arquivo real de forma persistente em produção, configure um armazenamento S3 compatível usando:

- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_BUCKET`
- `S3_REGION` (opcional)
- `S3_PUBLIC_BASE_URL` (opcional)

Sem essas variáveis, o sistema registra o nome, tamanho e checksum do arquivo, mas não conserva os bytes do upload.

## Login inicial

Por padrão, se as variáveis não forem definidas:

- usuário: `admin`
- senha: `admin123`

Em produção, configure `LEGACY_ADMIN_USER` e `LEGACY_ADMIN_PASSWORD` antes do primeiro acesso.

## Execução local

```bash
cd legacy_system
pip install -r requirements.txt
export DATABASE_URL='postgresql://...'
python app.py
```

## Deploy

O serviço deve iniciar com:

```bash
gunicorn app:app
```

Root directory: `legacy_system`.
