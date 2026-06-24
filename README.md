# RemoteCC — Compilação Remota de C/C++

> Aplicação distribuída cliente/servidor para envio, compilação e retorno de arquivos C/C++.

---

## Sumário

1. [Propósito da Aplicação](#1-propósito-da-aplicação)
2. [Motivação para o Protocolo de Transporte](#2-motivação-para-o-protocolo-de-transporte)
3. [Requisitos Mínimos de Funcionamento](#3-requisitos-mínimos-de-funcionamento)
4. [Visão Geral da Arquitetura](#4-visão-geral-da-arquitetura)
5. [Protocolo da Camada de Aplicação (RCP — Remote Compile Protocol)](#5-protocolo-da-camada-de-aplicação-rcp--remote-compile-protocol)
   - 5.1 [Formato das Mensagens](#51-formato-das-mensagens)
   - 5.2 [Tipos de Mensagem](#52-tipos-de-mensagem)
   - 5.3 [Códigos de Status](#53-códigos-de-status)
   - 5.4 [Estados do Cliente](#54-estados-do-cliente)
   - 5.5 [Estados do Servidor](#55-estados-do-servidor)
   - 5.6 [Fluxo Nominal (Happy Path)](#56-fluxo-nominal-happy-path)
   - 5.7 [Fluxos de Erro](#57-fluxos-de-erro)
   - 5.8 [Diagrama de Sequência Completo](#58-diagrama-de-sequência-completo)
6. [Eventos e Transições de Estado](#6-eventos-e-transições-de-estado)
   - 6.1 [Máquina de Estados do Cliente](#61-máquina-de-estados-do-cliente)
   - 6.2 [Máquina de Estados do Servidor](#62-máquina-de-estados-do-servidor)
7. [Regras e Restrições do Protocolo](#7-regras-e-restrições-do-protocolo)

---

## 1. Propósito da Aplicação

O **RemoteCC** é uma aplicação distribuída que permite a um cliente enviar um arquivo-fonte escrito em **C ou C++** a um servidor remoto, onde o arquivo é compilado utilizando as ferramentas disponíveis naquele ambiente (e.g., `gcc`, `g++`). O resultado — seja o binário compilado ou o log de erros de compilação — é devolvido ao cliente pela mesma conexão de rede.

### Casos de uso típicos

| Cenário | Descrição |
|---|---|
| Compilação cruzada | Compilar no servidor Linux enquanto o cliente usa Windows/macOS |
| CI/CD simplificado | Validar compilação de um trecho de código sem configurar toolchain local |
| Ambientes educacionais | Alunos enviam código para ser compilado e testado em um servidor centralizado |
| Laboratórios embarcados | Compilar para arquiteturas específicas disponíveis apenas no servidor |

---

## 2. Motivação para o Protocolo de Transporte

O RemoteCC utiliza **TCP** (_Transmission Control Protocol_) como protocolo de transporte pelas seguintes razões:

### Por que TCP e não UDP?

| Critério | TCP | UDP |
|---|---|---|
| **Integridade dos dados** | Garantida (retransmissão automática) | Não garantida |
| **Ordem de entrega** | Preservada | Pode chegar fora de ordem |
| **Controle de fluxo** | Sim | Não |
| **Orientado à conexão** | Sim (handshake explícito) | Não |
| **Adequação ao caso de uso** | ✅ Ideal | ❌ Inadequado |

### Justificativa detalhada

1. **Integridade do arquivo-fonte é crítica.** Um único byte corrompido em um arquivo `.c` ou `.cpp` pode gerar falha de compilação silenciosa ou código incorreto. O TCP garante entrega sem erros por meio de checksums e retransmissões.

2. **Arquivos podem ser grandes.** Fontes com cabeçalhos incluídos ou projetos maiores podem exceder a MTU padrão. O TCP fragmenta e remonta os segmentos de forma transparente, o que seria responsabilidade da aplicação caso UDP fosse usado.

3. **A conexão tem estado definido.** O protocolo RCP depende de uma sessão com fases bem definidas (handshake → envio → compilação → resposta → encerramento). O modelo orientado à conexão do TCP mapeia naturalmente a esse ciclo de vida.

4. **A latência não é requisito primário.** Diferente de aplicações de streaming ou jogos em tempo real, o RemoteCC prioriza confiabilidade e corretude sobre velocidade de transmissão.

---

## 3. Requisitos Mínimos de Funcionamento

### Servidor

| Requisito | Detalhe |
|---|---|
| Sistema operacional | Linux (Ubuntu 20.04+ recomendado) |
| Compilador | `gcc` ≥ 9.0 e/ou `g++` ≥ 9.0 instalado e no `PATH` |
| Python | ≥ 3.8 (para o processo servidor, se implementado em Python) |
| Porta de escuta | TCP 5000 (configurável) |
| Permissões | Permissão de escrita em diretório temporário (`/tmp` ou equivalente) |
| Conectividade | IP acessível pelo cliente (roteamento ou mesma LAN) |

### Cliente

| Requisito | Detalhe |
|---|---|
| Sistema operacional | Linux, macOS ou Windows |
| Python | ≥ 3.8 (ou runtime equivalente da linguagem de implementação) |
| Conectividade | Acesso TCP à porta do servidor |
| Arquivo-fonte | Arquivo `.c` ou `.cpp` válido no sistema de arquivos local |

### Dependências de Rede

- A porta TCP configurada deve estar **aberta no firewall** do servidor.
- Não há requisito de autenticação no protocolo base (pode ser adicionado como extensão).
- A latência de rede não impacta a corretude — apenas o tempo de resposta.

---

## 4. Visão Geral da Arquitetura

```
┌─────────────────────────────┐          ┌──────────────────────────────────┐
│           CLIENTE           │          │             SERVIDOR              │
│                             │  TCP/IP  │                                  │
│  [Arquivo .c/.cpp local]    │◄────────►│  [Recebe arquivo]                │
│                             │          │  [Executa gcc/g++]               │
│  [Recebe binário ou log]    │          │  [Retorna binário ou erro]       │
└─────────────────────────────┘          └──────────────────────────────────┘
         Camada de Aplicação: RCP (Remote Compile Protocol)
         Camada de Transporte: TCP
```

O servidor opera em modo **iterativo ou concorrente** (uma thread/processo por conexão). Cada sessão é independente e segue o ciclo de vida definido pelo protocolo RCP.

---

## 5. Protocolo da Camada de Aplicação (RCP — Remote Compile Protocol)

O **RCP** (_Remote Compile Protocol_) é um protocolo de camada de aplicação textual, baseado em troca de mensagens estruturadas sobre uma conexão TCP persistente. Cada sessão compreende as fases: **handshake**, **transferência**, **compilação** e **encerramento**.

---

### 5.1 Formato das Mensagens

Todas as mensagens seguem o formato:

```
<TIPO> <PARÂMETROS_OPCIONAIS>\r\n
[CORPO_OPCIONAL]\r\n
.\r\n
```

- **`<TIPO>`**: identificador da mensagem em maiúsculas (string ASCII).
- **`<PARÂMETROS_OPCIONAIS>`**: pares `chave=valor` separados por espaço.
- **Linha terminadora de corpo**: uma linha contendo apenas `.` (ponto) indica o fim do corpo. Mensagens sem corpo omitem essa linha.
- **Encoding**: UTF-8 para metadados; o corpo do arquivo é transmitido em **Base64** para garantir transparência binária.

**Exemplo de mensagem com corpo:**

```
SEND lang=c size=2048 filename=hello.c checksum=a3f5c2d1\r\n
I2luY2x1ZGUgPHN0ZGlvLmg+CgppbnQgbWFpbigpIHsKICAgIHByaW50ZigiSGVsbG8sIFdvcmxkIVxuIik7CiAgICByZXR1cm4gMDsKfQo=\r\n
.\r\n
```

---

### 5.2 Tipos de Mensagem

#### Mensagens enviadas pelo **Cliente**

| Mensagem | Parâmetros | Corpo | Descrição |
|---|---|---|---|
| `HELLO` | `version=<N>` | Não | Inicia a sessão e negocia versão do protocolo |
| `SEND` | `lang=<c\|cpp>` `size=<bytes>` `filename=<nome>` `checksum=<md5hex>` | Sim (arquivo em Base64) | Envia o arquivo-fonte para compilação |
| `OPTS` | `flags=<flags_gcc>` | Não | (Opcional) Define flags de compilação antes do `SEND` |
| `BYE` | — | Não | Encerra a sessão ordenaamente |

#### Mensagens enviadas pelo **Servidor**

| Mensagem | Parâmetros | Corpo | Descrição |
|---|---|---|---|
| `WELCOME` | `version=<N>` `server=<id>` | Não | Aceita a sessão e confirma versão negociada |
| `READY` | — | Não | Servidor pronto para receber o arquivo após `SEND` |
| `COMPILING` | — | Não | Compilação em andamento (keep-alive informativo) |
| `SUCCESS` | `size=<bytes>` `checksum=<md5hex>` | Sim (binário em Base64) | Compilação bem-sucedida; envia o binário resultante |
| `FAILURE` | `code=<exit_code>` | Sim (log de erros em texto) | Compilação falhou; envia o log de erros do compilador |
| `ERROR` | `code=<código>` `msg=<descrição>` | Não | Erro de protocolo ou do servidor |
| `BYE` | — | Não | Confirma encerramento da sessão |

---

### 5.3 Códigos de Status

Usados no parâmetro `code=` da mensagem `ERROR`:

| Código | Nome | Descrição |
|---|---|---|
| `100` | `UNSUPPORTED_VERSION` | Versão do protocolo não suportada pelo servidor |
| `101` | `UNSUPPORTED_LANG` | Linguagem não suportada (`lang` inválido) |
| `102` | `CHECKSUM_MISMATCH` | Checksum do arquivo recebido não confere |
| `103` | `FILE_TOO_LARGE` | Arquivo excede o limite máximo do servidor |
| `104` | `INVALID_MESSAGE` | Mensagem malformada ou fora de ordem |
| `105` | `SERVER_BUSY` | Servidor sem recursos disponíveis no momento |
| `200` | `COMPILE_OK` | (Informativo) Compilação concluída com sucesso |
| `201` | `COMPILE_ERROR` | Compilação concluída com erros (ver `FAILURE`) |
| `500` | `INTERNAL_ERROR` | Erro interno inesperado do servidor |

---

### 5.4 Estados do Cliente

| Estado | Descrição |
|---|---|
| `IDLE` | Estado inicial; sem conexão estabelecida |
| `CONNECTING` | Conexão TCP em andamento |
| `HANDSHAKING` | Aguardando `WELCOME` do servidor após envio de `HELLO` |
| `CONFIGURING` | (Opcional) Enviando `OPTS` antes do arquivo |
| `SENDING` | Enviando o arquivo-fonte via mensagem `SEND` |
| `AWAITING_RESULT` | Aguardando `SUCCESS` ou `FAILURE` do servidor |
| `RECEIVING` | Recebendo o binário ou log de erros do servidor |
| `CLOSING` | Enviou `BYE`; aguardando confirmação |
| `DONE` | Sessão encerrada com sucesso |
| `ERROR` | Sessão encerrada por erro irrecuperável |

---

### 5.5 Estados do Servidor

| Estado | Descrição |
|---|---|
| `LISTENING` | Aguardando conexões TCP na porta configurada |
| `ACCEPTING` | Conexão TCP aceita; aguardando `HELLO` do cliente |
| `NEGOTIATING` | Processando `HELLO`; enviando `WELCOME` |
| `IDLE_SESSION` | Sessão estabelecida; aguardando `SEND` ou `OPTS` |
| `RECEIVING_FILE` | Recebendo o corpo do arquivo após `SEND` |
| `VERIFYING` | Verificando checksum do arquivo recebido |
| `COMPILING` | Executando `gcc`/`g++` no arquivo recebido |
| `SENDING_RESULT` | Enviando `SUCCESS` (com binário) ou `FAILURE` (com log) |
| `CLOSING` | Recebeu `BYE`; confirmando encerramento |
| `DONE` | Sessão encerrada; recursos liberados |
| `ERROR` | Erro irrecuperável; conexão encerrada |

---

### 5.6 Fluxo Nominal (Happy Path)

O fluxo abaixo descreve uma sessão sem erros, com compilação bem-sucedida:

```
Cliente                                          Servidor
  |                                                 |
  |──── [Estabelece conexão TCP] ──────────────────►|
  |                                                 |
  |──── HELLO version=1 ───────────────────────────►|  (estado: NEGOTIATING)
  |◄─── WELCOME version=1 server=remotecc-01 ───────|
  |                                                 |
  | (opcional)                                      |
  |──── OPTS flags="-O2 -Wall" ────────────────────►|  (estado: IDLE_SESSION)
  |                                                 |
  |──── SEND lang=c size=512 filename=prog.c        |
  |          checksum=d41d8cd9 ────────────────────►|  (estado: RECEIVING_FILE)
  |──── [corpo Base64 do arquivo] ─────────────────►|
  |──── . ──────────────────────────────────────────►|
  |                                                 |
  |◄─── READY ──────────────────────────────────────|  (estado: VERIFYING)
  |◄─── COMPILING ──────────────────────────────────|  (estado: COMPILING)
  |                                                 |
  |◄─── SUCCESS size=8192 checksum=b1c2d3e4 ────────|  (estado: SENDING_RESULT)
  |◄─── [corpo Base64 do binário] ──────────────────|
  |◄─── . ──────────────────────────────────────────|
  |                                                 |
  |──── BYE ───────────────────────────────────────►|  (estado: CLOSING)
  |◄─── BYE ────────────────────────────────────────|
  |                                                 |
  |──── [Encerra conexão TCP] ──────────────────────►|
```

---

### 5.7 Fluxos de Erro

#### Erro de checksum

```
Cliente                                          Servidor
  |──── SEND lang=c size=512 ... checksum=XXXX ────►|
  |──── [corpo] ───────────────────────────────────►|  (estado: VERIFYING)
  |◄─── ERROR code=102 msg=checksum_mismatch ───────|  (estado: ERROR)
  |──── BYE ───────────────────────────────────────►|
  |◄─── BYE ────────────────────────────────────────|
```

#### Falha de compilação

```
Cliente                                          Servidor
  |◄─── COMPILING ──────────────────────────────────|  (estado: COMPILING)
  |◄─── FAILURE code=1 ─────────────────────────────|  (estado: SENDING_RESULT)
  |◄─── [log de erros do gcc em texto puro] ────────|
  |◄─── . ──────────────────────────────────────────|
  |──── BYE ───────────────────────────────────────►|
```

#### Versão de protocolo incompatível

```
Cliente                                          Servidor
  |──── HELLO version=99 ──────────────────────────►|
  |◄─── ERROR code=100 msg=unsupported_version ─────|  (estado: ERROR)
  |──── [Encerra conexão TCP] ──────────────────────►|
```

---

### 5.8 Diagrama de Sequência Completo

```
┌────────┐                                       ┌─────────┐
│CLIENTE │                                       │SERVIDOR │
└───┬────┘                                       └────┬────┘
    │                                                 │
    │    TCP SYN / SYN-ACK / ACK (3-way handshake)   │
    │◄───────────────────────────────────────────────►│
    │                                                 │
    │  HELLO version=1                                │
    │────────────────────────────────────────────────►│
    │                        WELCOME version=1 server=X
    │◄────────────────────────────────────────────────│
    │                                                 │
    │  OPTS flags="-O2"           (opcional)          │
    │────────────────────────────────────────────────►│
    │                                                 │
    │  SEND lang=c size=N filename=f.c checksum=HASH  │
    │────────────────────────────────────────────────►│
    │  <corpo Base64>                                 │
    │────────────────────────────────────────────────►│
    │  .                                              │
    │────────────────────────────────────────────────►│
    │                                         READY   │
    │◄────────────────────────────────────────────────│
    │                                     COMPILING   │
    │◄────────────────────────────────────────────────│
    │                                                 │
    │              [se compilação OK]                 │
    │                SUCCESS size=M checksum=HASH2    │
    │◄────────────────────────────────────────────────│
    │                <binário em Base64>              │
    │◄────────────────────────────────────────────────│
    │                .                                │
    │◄────────────────────────────────────────────────│
    │                                                 │
    │              [se compilação falhou]             │
    │                FAILURE code=<exit_code>         │
    │◄────────────────────────────────────────────────│
    │                <log de erros>                   │
    │◄────────────────────────────────────────────────│
    │                .                                │
    │◄────────────────────────────────────────────────│
    │                                                 │
    │  BYE                                            │
    │────────────────────────────────────────────────►│
    │                                           BYE   │
    │◄────────────────────────────────────────────────│
    │                                                 │
    │    TCP FIN / FIN-ACK / ACK (encerramento)      │
    │◄───────────────────────────────────────────────►│
┌───┴────┐                                       ┌────┴────┐
│CLIENTE │                                       │SERVIDOR │
└────────┘                                       └─────────┘
```

---

## 6. Eventos e Transições de Estado

### 6.1 Máquina de Estados do Cliente

```
                         ┌──────────────────────────────────────────────────────┐
                         │                      CLIENTE                         │
                         └──────────────────────────────────────────────────────┘

    [início]
       │
       ▼
  ┌─────────┐   conectar()    ┌────────────┐   TCP OK     ┌─────────────┐
  │  IDLE   │───────────────► │ CONNECTING │─────────────► │ HANDSHAKING │
  └─────────┘                 └────────────┘               └──────┬──────┘
                               │ falha TCP                        │
                               ▼                         recebe WELCOME
                           ┌───────┐                             │
                           │ ERROR │◄──────────────────────      ▼
                           └───────┘  recebe ERROR      ┌──────────────────┐
                               ▲      (qualquer estado)  │  IDLE_SESSION /  │
                               │                         │  CONFIGURING     │
                               │                         └────────┬─────────┘
                               │                                  │
                               │                         envia SEND
                               │                                  │
                               │                                  ▼
                               │                          ┌───────────────┐
                               │                          │    SENDING    │
                               │                          └───────┬───────┘
                               │                                  │
                               │                         recebe READY
                               │                                  │
                               │                                  ▼
                               │                       ┌──────────────────┐
                               │                       │ AWAITING_RESULT  │
                               │                       └────────┬─────────┘
                               │                                │
                               │              recebe SUCCESS ou FAILURE
                               │                                │
                               │                                ▼
                               │                       ┌────────────────┐
                               │                       │   RECEIVING    │
                               │                       └───────┬────────┘
                               │                               │ recebimento completo
                               │                               ▼
                               │                       ┌───────────────┐
                               └────── recebe ERROR ──►│    CLOSING    │◄── envia BYE
                                                        └───────┬───────┘
                                                                │ recebe BYE
                                                                ▼
                                                           ┌────────┐
                                                           │  DONE  │
                                                           └────────┘
```

**Tabela de transições — Cliente**

| Estado Atual | Evento | Próximo Estado | Ação |
|---|---|---|---|
| `IDLE` | `conectar()` | `CONNECTING` | Inicia conexão TCP |
| `CONNECTING` | TCP estabelecido | `HANDSHAKING` | Envia `HELLO version=1` |
| `CONNECTING` | Falha TCP | `ERROR` | Registra erro, encerra |
| `HANDSHAKING` | Recebe `WELCOME` | `IDLE_SESSION` | Sessão pronta |
| `HANDSHAKING` | Recebe `ERROR` | `ERROR` | Versão incompatível |
| `IDLE_SESSION` | `enviar_opts()` | `CONFIGURING` | Envia `OPTS` |
| `IDLE_SESSION` | `enviar_arquivo()` | `SENDING` | Envia `SEND` + corpo |
| `CONFIGURING` | `enviar_arquivo()` | `SENDING` | Envia `SEND` + corpo |
| `SENDING` | Recebe `READY` | `AWAITING_RESULT` | Aguarda compilação |
| `SENDING` | Recebe `ERROR` | `CLOSING` | Envia `BYE` |
| `AWAITING_RESULT` | Recebe `COMPILING` | `AWAITING_RESULT` | (keep-alive; aguarda) |
| `AWAITING_RESULT` | Recebe `SUCCESS` | `RECEIVING` | Inicia recebimento do binário |
| `AWAITING_RESULT` | Recebe `FAILURE` | `RECEIVING` | Inicia recebimento do log |
| `RECEIVING` | Corpo completo (`.`) | `CLOSING` | Envia `BYE`; salva resultado |
| `CLOSING` | Recebe `BYE` | `DONE` | Fecha socket TCP |
| `*` | Timeout ou desconexão | `ERROR` | Registra erro, fecha socket |

---

### 6.2 Máquina de Estados do Servidor

```
                    ┌──────────────────────────────────────────────────────┐
                    │                      SERVIDOR                        │
                    └──────────────────────────────────────────────────────┘

    [início]
       │
       ▼
  ┌───────────┐   conexão TCP     ┌───────────┐   recebe HELLO   ┌──────────────┐
  │ LISTENING │──────────────────►│ ACCEPTING │─────────────────►│ NEGOTIATING  │
  └───────────┘                   └───────────┘                  └──────┬───────┘
        ▲                                                                │
        │                                                       versão OK│
        │                                               envia WELCOME    │
        │                                                                ▼
        │                                                      ┌──────────────────┐
        │                                                      │   IDLE_SESSION   │
        │                                                      └────────┬─────────┘
        │                                                               │
        │                                                   recebe SEND │
        │                                                               ▼
        │                                                    ┌──────────────────┐
        │                                                    │ RECEIVING_FILE   │
        │                                                    └────────┬─────────┘
        │                                                             │ corpo completo
        │                                                             ▼
        │                    ┌──────────────────────────────┌──────────────────┐
        │                    │  checksum inválido           │   VERIFYING      │
        │                    ▼                              └────────┬─────────┘
        │             ┌───────────┐ envia ERROR                     │ checksum OK
        │             │   ERROR   │                                  ▼
        │             └─────┬─────┘                       ┌──────────────────┐
        │                   │                             │    COMPILING     │
        │                   │                             └────────┬─────────┘
        │                   │                                      │
        │                   │              ┌───────────────────────┤
        │                   │              │ gcc OK                │ gcc falhou
        │                   │              ▼                       ▼
        │                   │    ┌──────────────────┐   ┌──────────────────┐
        │                   │    │ SENDING_RESULT   │   │ SENDING_RESULT   │
        │                   │    │ (SUCCESS+binário)│   │ (FAILURE+log)    │
        │                   │    └────────┬─────────┘   └────────┬─────────┘
        │                   │             └──────────┬───────────┘
        │                   │                        │ envio completo
        │                   │                        ▼
        │                   │              ┌──────────────────┐
        │                   │              │     CLOSING      │◄── recebe BYE
        │                   │              └────────┬─────────┘
        │                   │                       │ envia BYE
        │                   │                       ▼
        └───────────────────┴──────────── ┌──────────────────┐
                                          │       DONE       │──► libera recursos
                                          └──────────────────┘    volta a LISTENING
```

**Tabela de transições — Servidor**

| Estado Atual | Evento | Próximo Estado | Ação |
|---|---|---|---|
| `LISTENING` | Nova conexão TCP aceita | `ACCEPTING` | Cria contexto de sessão |
| `ACCEPTING` | Recebe `HELLO` | `NEGOTIATING` | Verifica versão |
| `NEGOTIATING` | Versão suportada | `IDLE_SESSION` | Envia `WELCOME` |
| `NEGOTIATING` | Versão inválida | `ERROR` | Envia `ERROR code=100` |
| `IDLE_SESSION` | Recebe `OPTS` | `IDLE_SESSION` | Armazena flags de compilação |
| `IDLE_SESSION` | Recebe `SEND` | `RECEIVING_FILE` | Inicia recepção do corpo |
| `RECEIVING_FILE` | Linha `.` recebida | `VERIFYING` | Calcula checksum |
| `VERIFYING` | Checksum OK | `COMPILING` | Envia `READY`; inicia gcc/g++ |
| `VERIFYING` | Checksum inválido | `ERROR` | Envia `ERROR code=102` |
| `COMPILING` | (periódico, > 5s) | `COMPILING` | Envia `COMPILING` (keep-alive) |
| `COMPILING` | gcc retorna 0 | `SENDING_RESULT` | Envia `SUCCESS` + binário em Base64 |
| `COMPILING` | gcc retorna ≠ 0 | `SENDING_RESULT` | Envia `FAILURE` + log de erros |
| `SENDING_RESULT` | Envio completo (`.`) | `CLOSING` | Aguarda `BYE` |
| `CLOSING` | Recebe `BYE` | `DONE` | Envia `BYE`; fecha socket |
| `DONE` | — | `LISTENING` | Libera recursos; aceita nova conexão |
| `*` | Timeout (30s sem atividade) | `ERROR` | Fecha socket, libera recursos |
| `*` | Desconexão inesperada | `ERROR` | Limpa arquivos temporários |

---

## 7. Regras e Restrições do Protocolo

1. **Ordenação obrigatória de mensagens.** O cliente **deve** enviar `HELLO` antes de qualquer outra mensagem. Mensagens fora de ordem resultam em `ERROR code=104`.

2. **`OPTS` é opcional e deve preceder `SEND`.** Se enviado após `SEND`, o servidor responde com `ERROR code=104`.

3. **Checksum obrigatório.** O cliente calcula o MD5 do conteúdo **original** do arquivo (antes da codificação Base64) e o informa no parâmetro `checksum=`. O servidor verifica após decodificar o Base64.

4. **Limite de tamanho.** O servidor pode impor um limite máximo de arquivo (ex: 10 MB). Arquivos que excederem esse limite recebem `ERROR code=103` imediatamente após `SEND`.

5. **Keep-alive durante compilação.** Para compilações longas (> 5 segundos), o servidor envia mensagens `COMPILING` periódicas para evitar timeout no cliente.

6. **Timeout de sessão.** Sessões sem atividade por mais de **30 segundos** em qualquer estado são encerradas unilateralmente pelo servidor.

7. **Encerramento gracioso.** O `BYE` do cliente deve aguardar o `BYE` de confirmação do servidor antes de fechar o socket TCP.

8. **Versão do protocolo.** A versão atual é `1`. Clientes que enviarem versões superiores à suportada pelo servidor recebem `ERROR code=100` e a conexão é encerrada.

9. **Limpeza de arquivos temporários.** O servidor deve remover todos os arquivos temporários (fonte, objeto, binário) ao encerrar uma sessão, com sucesso ou com erro.

10. **Concorrência.** Cada conexão TCP é tratada de forma independente. O protocolo não define comportamento de sessões compartilhadas ou filas de compilação.

---

*Versão do protocolo: RCP/1 — Documento atualizado conforme especificação inicial.*
