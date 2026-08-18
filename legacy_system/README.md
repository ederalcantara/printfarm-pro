# Sistema Legacy v1

Nova base do Sistema Legacy, construída separadamente do sistema antigo.

## Fluxo principal de orçamento e produção

1. `draft` — orçamento em montagem.
2. `awaiting_customer_approval` — enviado ao cliente, aguardando aprovação.
3. `approved_for_execution` — aprovado pelo cliente e liberado para preparação técnica.
4. `preparing` — ajustes de tamanho, orientação, suporte, fatiamento e parâmetros.
5. `printing` — entrou na fila/impressão. **Neste ponto o estoque é baixado automaticamente uma única vez.**
6. `completed` — impressão concluída.
7. `delivered` — entregue ao cliente.
8. `cancelled` — cancelado.

## Regra de estoque

O orçamento não reduz estoque. A baixa acontece somente na primeira transição para `printing`.

A movimentação é idempotente: se o status for salvo novamente como `printing`, o estoque não é descontado uma segunda vez.

Para cada item de produção guardamos:
- consumo estimado em gramas;
- consumo efetivamente baixado;
- data da baixa;
- histórico da movimentação.

Na conclusão, uma versão futura poderá ajustar diferença entre peso estimado e peso real.

## Módulos da primeira fase

- clientes;
- materiais/filamentos;
- orçamentos;
- itens do orçamento;
- fluxo de aprovação/produção;
- baixa automática de estoque;
- histórico de estoque;
- BRL/USD por orçamento.

## Banco

PostgreSQL via `DATABASE_URL`.
