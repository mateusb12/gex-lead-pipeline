# Conceitual — Parte B: Decisões de arquitetura

## 1. Idempotência

A chave não pode ser só `transaction_id`, porque `transaction_id` identifica o pedido, mas não diz qual evento aconteceu naquele pedido.

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

É o mesmo pedido, mas não é o mesmo acontecimento. Se eu usar só `transaction_id`, o refund pode ser barrado como duplicado do approved. Isso seria errado.

Por isso a chave natural do desafio é:

```text
transaction_id + event
```

Com essa chave, fica assim:

```text
WHEY-123 + order.approved -> entra uma vez
WHEY-123 + order.approved -> duplicado, não republica
WHEY-123 + order.refunded -> entra, porque é outro evento
```

O `event` permite que o pedido tenha uma história. Ele pode ser aprovado, recusado ou estornado em momentos diferentes. O que não pode acontecer é o mesmo evento do mesmo pedido gerar o mesmo efeito duas vezes.

Onde cada chave falha:

```text
só transaction_id
-> falha quando o mesmo pedido tem mais de um evento válido

transaction_id + event
-> falharia se o negócio precisasse aceitar duas ocorrências iguais do mesmo evento como coisas diferentes
```

Para esse desafio, a segunda situação não é o caso esperado. A regra é justamente: o mesmo pedido pode ter eventos diferentes, mas a mesma combinação pedido + evento não deve ser processada duas vezes.

Na implementação eu ainda uso:

```text
gateway + transaction_id + event
```

Faço isso porque não dá para assumir que `lous` e `grummer` usam o mesmo padrão de identificador.

Exemplo:

```text
lous    + WHEY-123 + order.approved
grummer + WHEY-123 + order.approved
```

Esses dois registros podem ser vendas diferentes. Sem o `gateway`, uma venda real poderia ser ignorada só porque outro provedor usou o mesmo `transaction_id`.

Então a ideia é simples: `transaction_id + event` resolve a idempotência do evento. `gateway + transaction_id + event` deixa isso seguro para múltiplos gateways.

## 2. Criptografia

Para um webhook novo da GEX, eu escolheria **AES-256-GCM**.

Eu só usaria AES-256-CBC por compatibilidade com um gateway legado, como no caso do Grummer. Para um desenho novo, eu iria de GCM porque ele já é um modo autenticado.

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

O CBC puro é perigoso porque ele não protege sozinho contra manipulação do ciphertext. Sem MAC/autenticação, ele pode permitir alteração de blocos sem detecção adequada. Dependendo de como a aplicação responde aos erros, também pode abrir espaço para padding oracle.

Com GCM, a autenticação faz parte do modo. Se alguém mexer no ciphertext ou na tag, a validação falha e o payload não entra na esteira.

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

Agora, 90% de erro é outra coisa. **A falha deixou de ser exceção e virou regra**.

RabbitMQ + retry exponencial + DLQ ajuda, mas não basta.

DLQ responde:

```text
essa mensagem falhou, vou guardar para reprocessar depois
```

Backpressure responde:

```text
o sistema está gastando recurso demais em uma falha repetitiva
então eu preciso desacelerar ou isolar esse canal
```

Exemplo:

```text
10.000 mensagens em dist.sms
90% falhando
3 retries por mensagem
```

Mesmo que tudo acabe indo para DLQ, antes disso o sistema gastou worker, conexão HTTP, tempo, CPU, memória, logs e fila tentando milhares de chamadas que provavelmente já iam falhar.

Eu trataria SMS como um canal com saúde própria. A política seria parecida com uma curva de fan de GPU: 
- você vai jogando o jogo
- o chip gráfico vai esquentando
- a reação do cooler muda de acordo com a temperatura

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

O ponto principal é isolar o incêndio. Se o SMS pegou fogo, eu não quero derrubar receiver, `lead.received`, Lead Worker, e-mail, call center, WhatsApp, `raw_payloads` e `lead_events` junto.

Eu reduzo ou pauso o consumo de `dist.sms`, mantenho os outros canais funcionando e gero alerta operacional. Só aplicaria backpressure mais acima se o problema do SMS começasse a contaminar infraestrutura compartilhada, como RabbitMQ, MySQL, CPU ou memória.

## 4. Migração Python -> Go

Eu não migraria receiver + decrypt de Python para Go por moda.

A pergunta principal é:

```text
onde está o gargalo real?
```

Python faz sentido nesse projeto porque o problema tem muita integração, JSON, validação, banco, fila, logs e regra de esteira. Nesse contexto, produtividade importa muito. **Hora de dev costuma ser mais cara do que alguns milissegundos de CPU.**

Eu consideraria migrar receiver + decrypt para Go se existissem sinais concretos de que Python virou o gargalo.

Migraria se:

1. **Receiver/decrypt virou gargalo medido**: CPU alta, p95/p99 subindo, fila crescendo antes do RabbitMQ ou tempo relevante gasto em parsing/decrypt/serialização.
2. **Custo de escalar Python ficou relevante**: muitos containers só para receber, validar e decriptar payload.
3. **Benchmark real mostrou ganho no caminho crítico**: usando payloads da GEX, concorrência parecida com produção e volume relevante.

Não migraria se:

1. **O gargalo está em I/O ou arquitetura**: MySQL, RabbitMQ, rede, provedor externo, retry mal desenhado ou falta de backpressure. Nesse caso, migrar para Go só deixa o sistema errado mais rápido.
2. **A equipe entrega e depura melhor em Python**: se Python atende volume e latência, trocar stack aumenta complexidade sem ganho claro.
3. **O ganho medido é pequeno ou fora do caminho crítico**: melhorar 35% de uma etapa irrelevante não paga custo de migração, manutenção, observabilidade nova e risco operacional.

Benchmark isolado não me convence. Se Go dá 35% de ganho em uma operação que dura 2ms e não segura a fila, eu não migraria. Agora, se esse ganho aparece no caminho crítico e roda em volume alto, aí começa a fazer sentido discutir.

Minha regra seria simples:

```text
Se o gargalo é linguagem/runtime, considero migrar.
Se o gargalo é arquitetura ou I/O, corrijo arquitetura/I/O.
```

No contexto da GEX, eu só migraria depois de medir. Não por preferência pessoal.
