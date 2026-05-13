# Conceitual — Parte B: Decisões de arquitetura

## 1. Idempotência

Eu não usaria só `transaction_id` como chave de idempotência.

`transaction_id` identifica o pedido dentro do gateway, mas não identifica sozinho o acontecimento de negócio. Um mesmo pedido pode ter eventos diferentes ao longo do tempo.

Exemplo:

```text
transaction_id = WHEY-123

sexta:
event = order.approved
payment.status = approved

segunda:
event = order.refunded
payment.status = refunded
```

Se a chave for só:

```text
transaction_id
```

o `order.refunded` pode ser tratado como duplicado do `order.approved`. Isso seria errado, porque o refund é um evento novo e legítimo.

A chave natural do desafio é:

```text
transaction_id + event
```

Com isso, o comportamento fica assim:

```text
WHEY-123 + order.approved -> processa uma vez
WHEY-123 + order.approved -> duplicate, não republica
WHEY-123 + order.refunded -> outro evento, pode entrar
```

A inclusão do `event` permite que o mesmo pedido tenha uma vida útil. Ele pode ser aprovado, estornado ou recusado em momentos diferentes. O que não pode acontecer é a mesma combinação `transaction_id + event` gerar efeito colateral duas vezes.

Na minha implementação, eu ainda incluo `gateway` na chave:

```text
gateway + transaction_id + event
```

Faço isso porque não dá para assumir que todos os gateways usam o mesmo namespace de `transaction_id`.

Exemplo:

```text
lous    + WHEY-123 + order.approved
grummer + WHEY-123 + order.approved
```

Esses dois eventos podem representar vendas diferentes. Sem `gateway`, eu posso marcar uma venda legítima como duplicada só porque dois provedores usaram o mesmo identificador.

O trade-off é que essa chave foi desenhada para eventos de negócio, não para registrar todas as tentativas de webhook.

A falha de usar só `transaction_id` é bloquear eventos legítimos do mesmo pedido.

A falha de usar `transaction_id + event` seria se o negócio precisasse tratar duas ocorrências iguais do mesmo evento como coisas independentes. Mas esse não é o caso descrito no desafio. O próprio enunciado diz que cada combinação pedido + tipo de evento só pode existir uma vez.

Então, para esse contexto, `transaction_id + event` é a chave correta. E `gateway + transaction_id + event` é a versão mais segura para a implementação, porque também evita colisão entre gateways diferentes.


## 2. Cripto

Para um webhook novo da GEX, eu escolheria **AES-256-GCM**.

Eu só usaria AES-256-CBC por compatibilidade com um gateway legado, como no caso do Grummer. Para um desenho novo, eu iria de GCM porque ele é um modo autenticado.

A diferença principal é:

```text
AES-CBC
-> cifra o conteúdo
-> não autentica o conteúdo sozinho
-> precisa de HMAC ou outra autenticação separada

AES-GCM
-> cifra o conteúdo
-> autentica o conteúdo
-> detecta alteração no payload
```

Em webhook de venda, integridade é tão importante quanto sigilo. Não basta esconder o payload. Eu preciso saber se ele chegou exatamente como o gateway enviou.

Exemplo com pedido de whey:

```text
payment.status: declined -> approved
quantity: 1 -> 10
amount_usd: 49.90 -> 499.00
product: Whey Basic -> Whey Premium
```

Se uma alteração dessas passar despercebida, a esteira pode gerar lead indevido, mandar o call center ligar para cliente errado, colocar o cliente na campanha errada ou distorcer relatório de vendas.

O CBC puro é perigoso porque ele não protege sozinho contra manipulação do ciphertext. Dependendo de como for implementado, pode abrir espaço para problemas como padding oracle e alteração de blocos sem detecção adequada.

Com GCM, a autenticação já faz parte do modo. Se alguém mexer no ciphertext ou nos dados autenticados, a validação falha e o payload não entra na esteira.

Resumo da decisão:

```text
Webhook novo -> AES-256-GCM
Webhook legado exigindo CBC -> CBC + autenticação separada, se possível
```

## 3. Backpressure

Se o canal SMS começa a falhar 90%, eu não trataria isso como erro individual normal.

Falha pontual é uma coisa:

```text
SMS falhou uma vez
-> retry
-> se esgotar, DLQ
```

Agora, 90% de erro é outra coisa. A falha deixou de ser exceção e virou a regra.

RabbitMQ + retry exponencial + DLQ ajuda, mas não basta.

DLQ responde:

```text
essa mensagem falhou, vou guardar para reprocessar depois
```

Backpressure responde:

```text
o sistema inteiro está gastando recurso demais em uma falha massiva,
então eu preciso desacelerar ou isolar esse canal
```

Exemplo:

```text
10.000 mensagens em dist.sms
90% falhando
3 retries por mensagem
```

Mesmo que tudo acabe indo para DLQ, antes disso o sistema gastou worker, conexão HTTP, tempo, CPU, memória, logs e fila tentando milhares de chamadas que provavelmente já iam falhar de qualquer forma.

Eu trataria SMS como um canal com saúde própria.

A política seria implementar um "healthcheck" parecida com curva de fan de GPU:

```text
erro normal
-> processa normalmente

erro alto por pouco tempo
-> retry e observação

erro alto persistente
-> reduz consumo de dist.sms

erro muito alto persistente
-> abre circuit breaker e pausa temporariamente SMS

provedor recuperou
-> volta aos poucos
```

O ponto principal é isolar o incêndio.

Se o SMS pegou fogo, eu não quero derrubar:

```text
receiver
lead.received
Lead Worker
e-mail
call center
WhatsApp
raw_payloads
lead_events
```

Eu reduzo ou pauso o consumo de `dist.sms`, mantenho os outros canais funcionando e gero alerta operacional.

A exceção seria se o problema do SMS começasse a contaminar infraestrutura compartilhada, como RabbitMQ, MySQL, CPU ou memória. Aí sim eu aplicaria backpressure mais acima, inclusive reduzindo entrada no receiver ou retornando erro temporário. Mas se o problema é localizado no SMS, eu não mataria a esteira inteira.

## 4. Migração entre linguagens

Eu não migraria receiver + decrypt de Python para Go por moda.

A pergunta principal é:

```text
onde está o gargalo real?
```

Python faz sentido nesse projeto porque o problema tem muita integração, JSON, validação, banco, fila, logs e regras de esteira. Nesse contexto, produtividade importa muito. Hora de dev costuma ser mais cara do que alguns milissegundos de CPU.

Eu consideraria migrar receiver + decrypt para Go se existissem sinais concretos de que Python virou o gargalo.

### Sinais de que vale considerar migração

1. **Receiver/decrypt virou gargalo medido**

Exemplo:

```text
CPU alta no receiver
p95/p99 subindo
fila crescendo antes de chegar no RabbitMQ
tempo relevante sendo gasto em parsing/decrypt/serialização
```

Nesse caso, faz sentido testar Go, porque ele tende a ser mais eficiente em CPU, memória e concorrência.

2. **Custo de escalar Python ficou relevante**

Se para aguentar o volume de webhooks eu preciso subir muitos containers só para receber, validar e decriptar payload, talvez exista economia real migrando uma parte pequena e quente da esteira.

3. **Benchmark real mostra ganho no caminho crítico**

Benchmark isolado não me convence. Eu precisaria testar com payloads reais da GEX, concorrência parecida com produção e volume relevante.

Se Go dá 35% de ganho em uma operação que dura 2ms e não é gargalo, eu não migraria.

Agora, se esse ganho aparece no caminho crítico e roda bilhões de vezes por mês, aí começa a fazer sentido discutir.

### Sinais de que NÃO vale migrar

1. **O gargalo está em I/O ou arquitetura**

Se o problema está em MySQL, RabbitMQ, rede, provedor externo, retry mal desenhado ou falta de backpressure, migrar para Go não resolve.

Você só fica com um sistema errado mais rápido.

2. **A equipe entrega e depura melhor em Python**

Se Python está atendendo volume e latência, e a equipe consegue mexer rápido com segurança, migrar aumenta complexidade sem ganho claro.

3. **O ganho medido é pequeno ou fora do caminho crítico**

Melhorar 35% de uma etapa irrelevante não paga o custo de migração, manutenção, mudança de stack, observabilidade nova e risco operacional.

Minha regra seria simples:

```text
Se o gargalo é linguagem/runtime, considero migrar.
Se o gargalo é arquitetura ou I/O, corrijo arquitetura/I/O.
```

No contexto da GEX, eu só migraria depois de medir. Não por preferência pessoal.