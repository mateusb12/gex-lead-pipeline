# Conceitual — Parte B: Decisões de arquitetura

## 1. Idempotência

Eu não usaria apenas `transaction_id`. Ele identifica o pedido dentro do gateway, mas não o acontecimento de negócio. Um pedido de whey pode nascer aprovado, ser estornado depois e ainda assim continuar sendo o mesmo `transaction_id`.

A chave natural é:

```text
transaction_id + event
```

Com isso:

```text
WHEY-123 + order.approved -> processa uma vez
WHEY-123 + order.approved -> duplicado
WHEY-123 + order.refunded -> evento novo
```

Usar só `transaction_id` falha quando o mesmo pedido tem `declined`, `approved` e `refunded` em momentos diferentes. O segundo evento legítimo seria esmagado como se fosse retry.

Na implementação, incluo também `gateway`:

```text
gateway + transaction_id + event
```

Isso evita colisão entre provedores distintos que reutilizem o mesmo identificador. A composição com `event` só falharia se o negócio quisesse tratar duas ocorrências iguais do mesmo evento como independentes, mas esse não é o caso do desafio. Aqui o objetivo é justamente bloquear o mesmo efeito repetido.

## 2. Criptografia

Para um webhook novo, eu escolheria **AES-256-GCM**. O CBC usado no Grummer é aceitável por compatibilidade, mas não autentica o conteúdo sozinho.

```text
AES-CBC -> confidencialidade; precisa de autenticação adicional
AES-GCM -> confidencialidade + integridade autenticada
```

Em dados de venda, integridade é tão importante quanto sigilo. Mudar `status`, `quantity` ou `amount` sem detecção gera lead incorreto, distorce operação e pode colocar o time comercial atrás da pessoa errada. Para legado em CBC, eu exigiria autenticação separada quando possível.

Sem MAC/autenticação, CBC permite manipulação/malleability de blocos sem detecção; se a aplicação expõe diferenças entre erro de padding e erro de decrypt, também abre espaço para padding oracle. GCM evita esses cenários ao autenticar ciphertext e tag antes de aceitar o payload.

No exemplo do pedido de whey, `payment.status: declined -> approved` ou `quantity: 1 -> 10` não são detalhes cosméticos. São alterações que mudam quem entra na esteira e como a operação reage. Por isso, para webhook novo, minha escolha é GCM sem hesitar.

## 3. Backpressure

Se SMS falha 90%, retry e DLQ ajudam, mas não bastam. DLQ guarda a falha individual; backpressure protege o sistema de gastar recurso infinito numa falha que virou regra. Sem isso, o sistema desperdiça worker, fila, conexões HTTP e logs tentando uma avalanche previsível.

RabbitMQ + retry exponencial sozinho ainda deixa o canal ruim comandar o ritmo do sistema. Com 10 mil mensagens, 90% de falha e múltiplas tentativas, o backlog cresce, a fila fica cada vez mais velha e você segue pagando custo por uma chance de sucesso que já ficou improvável.

Eu trataria SMS como canal isolado:

```text
erro pontual -> retry
erro alto persistente -> reduzir consumo
erro muito alto persistente -> circuit breaker/pausa do canal
recuperação -> retomada gradual
```

Receiver, `lead.received`, Lead Worker, banco e demais canais devem continuar vivos. A lógica se parece mais com curva de fan de GPU do que com um if isolado: a resposta sobe conforme o calor sobe. Só aplicaria backpressure mais acima se o problema do SMS começasse a degradar recursos compartilhados.

Enquanto a falha estiver localizada, eu reduziria o consumo de `dist.sms`, manteria os outros canais andando e abriria alerta operacional. Se o provedor recuperar, a volta também deve ser gradual; despejar todo o backlog de uma vez pode recriar a sobrecarga.

## 4. Migração Python -> Go

Eu só migraria receiver + decrypt depois de medir gargalo real. Não migraria por moda só porque Go parece uma escolha mais performática no papel.

Migraria se:

1. CPU do receiver/decrypt for gargalo medido.
2. p95/p99 subir e a fila crescer antes do RabbitMQ.
3. custo de escalar Python ficar relevante em benchmark real com payloads da GEX.

Não migraria se:

1. gargalo estiver em MySQL, RabbitMQ, rede, retry ou provedor externo.
2. ganho vier só de microbenchmark fora do caminho crítico.
3. a equipe entrega e depura melhor em Python e o sistema ainda atende volume/latência.

Esse ponto de benchmark importa. Ganhar 35% em cima de uma etapa de 2 ms que não segura a fila não paga troca de stack, observabilidade nova e custo operacional. Ganhar 35% no caminho crítico, em volume alto e com fila se formando antes do RabbitMQ, já merece conversa séria.

Regra prática:

```text
gargalo de runtime -> avaliar Go
gargalo de arquitetura ou I/O -> corrigir arquitetura ou I/O
```
