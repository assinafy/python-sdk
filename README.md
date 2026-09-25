# SDK Python da Assinafy

*Português · [Read in English](README.en.md)*

SDK oficial em Python para a [API Assinafy](https://api.assinafy.com.br/v1/docs) — plataforma
brasileira de assinatura eletrônica de documentos.

O SDK é síncrono, construído sobre `httpx`, e cobre as 93 operações publicadas hoje pela Assinafy:
contas, usuários, autenticação, OAuth, documentos, signatários, documentos do signatário,
assignments, definições de campo, templates, tags e webhooks. Todo método público nomeia o verbo e o
caminho que chama e documenta o corpo da requisição e a resposta já desembrulhada; os formatos de
recurso compartilhados são documentados uma vez e referenciados pelos métodos que os devolvem.

- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Autenticação](#autenticação)
  - [Configuração do cliente](#configuração-do-cliente)
- [Início rápido](#início-rápido)
- [Métodos de verificação do signatário](#métodos-de-verificação-do-signatário)
  - [Certificado digital ICP-Brasil (A1/A3)](#certificado-digital-icp-brasil-a1a3)
- [O ciclo de vida da assinatura](#o-ciclo-de-vida-da-assinatura)
  - [1. Prepare os signatários](#1-prepare-os-signatários)
  - [2. Envie o documento](#2-envie-o-documento)
  - [3. Estime o custo](#3-estime-o-custo)
  - [4. Solicite as assinaturas](#4-solicite-as-assinaturas)
  - [5. O lado do signatário](#5-o-lado-do-signatário)
  - [6. Acompanhe o progresso](#6-acompanhe-o-progresso)
  - [7. Baixe o documento assinado](#7-baixe-o-documento-assinado)
  - [Partindo de um template](#partindo-de-um-template)
- [OAuth para aplicações de marketplace](#oauth-para-aplicações-de-marketplace)
  - [1. Registre a aplicação](#1-registre-a-aplicação)
  - [2. Leve o usuário até a Assinafy](#2-leve-o-usuário-até-a-assinafy)
  - [3. Trate o callback e troque o código](#3-trate-o-callback-e-troque-o-código)
  - [4. Chame a API](#4-chame-a-api)
  - [5. Renove e desconecte](#5-renove-e-desconecte)
  - [Descoberta e OpenID Connect](#descoberta-e-openid-connect)
  - [Checklist de OAuth](#checklist-de-oauth)
- [Referência por recurso](#referência-por-recurso)
  - [Autenticação](#autenticação-1)
  - [Contas](#contas)
  - [Usuário autenticado](#usuário-autenticado)
  - [Documentos](#documentos)
  - [Templates](#templates)
  - [Tags](#tags)
  - [Signatários](#signatários)
  - [Assignments](#assignments)
  - [OAuth](#oauth)
  - [Documentos do signatário](#documentos-do-signatário)
  - [Definições de campo](#definições-de-campo)
  - [Webhooks](#webhooks)
- [Parâmetros de consulta](#parâmetros-de-consulta)
- [Formatos de resposta](#formatos-de-resposta)
- [Erros](#erros)
- [Ambientes](#ambientes)
- [Desenvolvimento](#desenvolvimento)
- [Documentação](#documentação)
- [Licença](#licença)

## Requisitos

- Python 3.10+
- `httpx` (instalado automaticamente)
- TLS 1.2 ou superior: o cliente recusa TLS 1.0 e 1.1

## Instalação

```bash
pip install assinafy
```

## Autenticação

Prefira `api_key` — é enviada no header documentado `X-Api-Key`. `token` envia
`Authorization: Bearer <token>`, para fluxos de token de usuário. Se os dois forem informados, a
chave de API tem precedência.

```python
client = AssinafyClient(api_key="k_xxx", account_id="acc_xxx")
client = AssinafyClient(token="jwt_xxx", account_id="acc_xxx")
```

O SDK **retém** as duas credenciais nas rotas cuja segurança publicada é pública ou apenas por
código de acesso do signatário — assim uma chave de API nunca é enviada a um endpoint que não a
espera. Toda requisição de produção e sandbox usa
`User-Agent: Assinafy-Python-SDK/v<versão-do-pacote>`.

Clientes sem autenticação são permitidos, para endpoints públicos e por código de acesso:

```python
public_client = AssinafyClient()
session = public_client.authentication.login("usuario@example.com", "senha")
```

Há quatro formas de autenticar, e a escolha depende de *qual* workspace você está operando:

| Modo | Enviado como | Use quando |
| --- | --- | --- |
| Chave de API | `X-Api-Key` | você automatiza o **seu próprio** workspace — recomendado para back ends |
| Token de acesso | `Authorization: Bearer` | você tem uma sessão de usuário obtida em `authentication.login()` |
| Código de acesso do signatário | parâmetro de consulta `signer-access-code` | você conduz os endpoints voltados ao signatário |
| OAuth 2.1 + PKCE | `Authorization: Bearer` | você constrói um app que **outras pessoas** conectam ao workspace delas — veja [OAuth para aplicações de marketplace](#oauth-para-aplicações-de-marketplace) |

### Configuração do cliente

| Parâmetro | Tipo | Padrão | Descrição |
| --- | --- | --- | --- |
| `api_key` | str | None | Enviada como `X-Api-Key`. |
| `token` | str | None | Enviado como `Authorization: Bearer <token>`. |
| `account_id` | str | None | ID padrão da conta / workspace para métodos com escopo de conta. |
| `base_url` | str | `https://api.assinafy.com.br/v1` | URL base da API. |
| `webhook_secret` | str | None | Segredo usado pelo `WebhookVerifier`. |
| `timeout` | float | `30.0` | Timeout da requisição, em segundos. |
| `logger` | object | no-op | Objeto com métodos `debug/info/warning/error`. |

Use `https://sandbox.assinafy.com.br/v1` como `base_url` para trabalhar no sandbox.

A `base_url` deve conter apenas esquema, host, porta e caminho. O construtor **rejeita** uma URL que
embuta credenciais (`https://usuario:senha@host/v1`, que substituiria silenciosamente sua chave de
API por autenticação HTTP Basic) ou que carregue query string ou fragmento (que colaria o caminho da
requisição no componente errado da URL).

`http://` em texto puro é rejeitado para qualquer host que não seja loopback: `login`,
`social_login`, `change_password`, `reset_password` e `create_api_key` enviam segredos no corpo da
requisição mesmo quando o cliente não tem `api_key` nem `token`, então a interface de loopback é o
único lugar onde texto puro é seguro. Aponte servidores locais e de mock para
`localhost`/`127.0.0.1`.

O cliente é um context manager e mantém um pool de conexões HTTP — use `with` ou chame `close()` ao
terminar.

## Início rápido

`upload_and_request_signatures` executa o caso comum de ponta a ponta:

```python
import os
from assinafy import AssinafyClient

with AssinafyClient(
    api_key=os.environ["ASSINAFY_API_KEY"],
    account_id=os.environ["ASSINAFY_ACCOUNT_ID"],
    webhook_secret=os.environ.get("ASSINAFY_WEBHOOK_SECRET"),
) as client:
    resultado = client.upload_and_request_signatures(
        source={"file_path": "./contrato.pdf"},
        signers=[
            {"full_name": "João Silva", "email": "joao@example.com"},
            {"full_name": "Maria Souza", "email": "maria@example.com"},
        ],
        message="Por favor, assine este contrato",
    )

    print(resultado["document"]["id"])
```

Ele encadeia três chamadas — upload, criação de cada signatário e criação do assignment — e **não é
transacional**: uma falha no meio do caminho não desfaz o que já deu certo. Todo `AssinafyError`
levantado depois do upload carrega `document_id` e os `signer_ids` já criados no seu `context`, para
que você possa apagar os órfãos ou repetir os passos restantes. Aceita também `wait_timeout` /
`wait_poll_interval` para sobrescrever o polling padrão de prontidão do documento.

Signatários só com telefone usam verificação e notificação por WhatsApp, o que exige
disponibilidade na conta e consome créditos — use `assignments.estimate_cost()` quando o custo
precisar ser conhecido antes do envio.

Quando você precisar de IDs explícitos, controle de custo ou limpeza, conduza o mesmo ciclo de vida
pelos recursos individuais — é o que a próxima seção percorre.

## Métodos de verificação do signatário

Definidos por signatário em `verification_method` ao criar o assignment. O método de verificação e o
de notificação são **acoplados**: envie um, os dois ou nenhum — o lado que faltar é inferido. Sem
nenhum dos dois, ambos assumem `Email`.

| Método | Como funciona | Custo por signatário |
| --- | --- | --- |
| `Email` *(padrão)* | Código de uso único (OTP) por e-mail, exigido antes de assinar | Gratuito |
| `Whatsapp` | Código de uso único (OTP) por WhatsApp | Verificação gratuita; a notificação que ela exige custa 0,45 crédito, só em planos pagos |
| `DigitalCertificate` | O signatário assina com o **próprio certificado ICP-Brasil (A1/A3)**, pela extensão de navegador Web PKI, gerando uma assinatura **PAdES qualificada** | 2 créditos, mais a notificação |

Combinações permitidas: `Email` → notifica por `Email`; `Whatsapp` → notifica por `Whatsapp`;
`DigitalCertificate` → notifica por `Email` **ou** `Whatsapp`. Apenas um método de notificação por
signatário, e uma combinação inválida responde `400`.

### Certificado digital ICP-Brasil (A1/A3)

Exige o recurso **Certificado Digital** na conta (planos Standard e Pro), CPF ou CNPJ em
`government_id` do signatário, e exatamente **um signatário por certificado naquele passo**. Um CPF
exige o certificado daquela pessoa (e-CPF, ou e-CNPJ que a nomeie como representante legal); um CNPJ
exige um e-CNPJ da empresa.

```python
signatario = client.signers.update(signer_id, {"government_id": "39053344705"})

custo = client.assignments.estimate_cost(document_id, {
    "method": "virtual",
    "signers": [{"verification_method": "DigitalCertificate",
                 "notification_methods": ["Email"]}],
})

client.assignments.create(document_id, {
    "method": "virtual",
    "signers": [{
        "id": signatario["id"],
        "step": 1,
        "verification_method": "DigitalCertificate",
        "notification_methods": ["Email"],
    }],
})
```

Antes de abrir o assignment, o signatário precisa confirmar os dados de identidade **e** aceitar os
termos — `confirm_data(..., {"has_accepted_terms": True})` resolve os dois em uma chamada, e
`accept_terms()` nunca é bloqueado. Passar `has_accepted_terms` para `get_for_signer()` é tarde
demais para abrir essa trava.

O endpoint comum de assinatura **rejeita** signatários por certificado: a assinatura deles é
produzida por um handshake de dois passos com a extensão Web PKI.

```
POST /v1/signers/certificate/start     -> data.token       (token da operação Web PKI)
        v  o navegador assina o token com o certificado do signatário
POST /v1/signers/certificate/complete  -> data.signerName
```

As duas rotas estão implantadas em produção e no sandbox, mas **não** constam como operações no
documento OpenAPI, então o contrato de requisição e resposta delas não é publicado e este SDK não as
chama — conduza esse passo pelo fluxo de assinatura hospedado pela Assinafy. Todo o resto está
coberto: criar o assignment, `confirm_data`, estimativa de custo e o download do artefato `pades`
depois que o fluxo termina.

## O ciclo de vida da assinatura

Um documento vai do upload ao PDF certificado em sete estágios. Cada estágio abaixo é uma chamada
real que você pode executar em ordem.

```python
import os
from assinafy import AssinafyClient

client = AssinafyClient(
    api_key=os.environ["ASSINAFY_API_KEY"],
    account_id=os.environ["ASSINAFY_ACCOUNT_ID"],
)
```

### 1. Prepare os signatários

Signatários são registros do workspace, reaproveitados entre documentos. Procure antes de criar uma
duplicata:

```python
signer = client.signers.find_by_email("signatario@example.com")
if signer is None:
    signer = client.signers.create({
        "full_name": "Signatário de Exemplo",
        "email": "signatario@example.com",
    })
```

Um signatário precisa de `full_name` mais pelo menos um canal de contato: `email` ou
`whatsapp_phone_number` no formato E.164 (`+5548999990000`). O canal informado determina como aquele
signatário pode ser verificado e notificado no estágio 4.

### 2. Envie o documento

Uploads usam o formato multipart documentado e são limitados localmente a PDFs de até 25 MB (a API
ainda limita documentos a 2000 páginas):

```python
document = client.documents.upload({"file_path": "./contrato.pdf"})
# ou, a partir da memória:
# client.documents.upload({"buffer": pdf_bytes, "file_name": "contrato.pdf"})
```

O documento fica em status `uploaded` enquanto a Assinafy renderiza as imagens das páginas e extrai
os metadados. Espere isso terminar antes de posicionar campos ou solicitar assinaturas:

```python
document = client.documents.wait_until_ready(document["id"])
```

`wait_until_ready` consulta `documents.get` até o status chegar a `metadata_ready`,
`pending_signature` ou `certificated`; levanta erro em um status de falha terminal e não repete um
`404`, que esperar nunca resolveria. Renomeie o documento aqui, se precisar — a API tranca o nome
assim que existe um assignment:

```python
document = client.documents.rename(document["id"], "Contrato de prestação de serviços.pdf")
```

### 3. Estime o custo

Criar um assignment envia notificações reais e consome créditos. Coloque preço antes, quando o custo
importa:

```python
estimativa = client.assignments.estimate_cost(document["id"], {
    "method": "virtual",
    "signers": [{
        "verification_method": "Email",
        "notification_methods": ["Email"],
    }],
})

if not estimativa["has_sufficient_resources"]:
    raise SystemExit(estimativa["blocking_reason"])
```

O corpo da estimativa aceita apenas descritores de preço — o SDK remove os IDs de signatário do fio,
já que não fazem parte do contrato de estimativa.

### 4. Solicite as assinaturas

Um assignment `virtual` pede a assinatura de cada signatário sem posicionar campos. `step` controla
a ordem: signatários no mesmo passo assinam em paralelo, e o passo seguinte é notificado quando o
anterior termina.

```python
assignment = client.assignments.create(document["id"], {
    "method": "virtual",
    "signers": [{
        "id": signer["id"],
        "verification_method": "Email",
        "notification_methods": ["Email"],
        "step": 1,
    }],
    "message": "Por favor, revise e assine.",
    "expires_at": "2030-12-31T23:59:59Z",
})
```

Um assignment `collect` posiciona campos reutilizáveis em páginas específicas, com `entries`:

```python
page = document["pages"][0]
field = client.fields.list()["data"][0]

assignment = client.assignments.create(document["id"], {
    "method": "collect",
    "signers": [{
        "id": signer["id"],
        "verification_method": "Email",
        "notification_methods": ["Email"],
        "step": 1,
    }],
    "entries": [{
        "page_id": page["id"],
        "fields": [{
            "signer_id": signer["id"],
            "field_id": field["id"],
            "display_settings": {
                "left": 69,
                "top": 282,
                "width": 421,
                "height": 45.86,
                "fontSize": 18,
                "fontFamily": "Arial",
                "backgroundColor": "#D5EBFF",
            },
        }],
    }],
})
```

`left`, `top`, `width`, `height` e `fontSize` são valores obrigatórios em pixels da imagem da página
a 150 DPI, medidos do canto superior esquerdo; largura, altura e tamanho de fonte devem ser
positivos e as coordenadas não negativas. A API não corta retângulos fora dos limites, então
mantenha o posicionamento dentro do `width`/`height` informado pela página. `fontFamily` e
`backgroundColor` são metadados de apresentação opcionais.

`DigitalCertificate` também é aceito como `verification_method`; veja
[Certificado digital ICP-Brasil (A1/A3)](#certificado-digital-icp-brasil-a1a3) para os requisitos, o
custo, e por que o SDK para antes do handshake da assinatura em si.

Com o assignment criado, você pode ajustar ou reenviar as notificações:

```python
client.assignments.reset_expiration(document["id"], assignment["id"], "2031-01-31T00:00:00Z")
client.assignments.reset_expiration(document["id"], assignment["id"], None)  # remove a expiração
client.assignments.estimate_resend_cost(document["id"], assignment["id"], signer["id"])
client.assignments.resend_notification(document["id"], assignment["id"], signer["id"])
client.assignments.whatsapp_notifications(document["id"], assignment["id"])
```

`resend_notification()` envia uma mensagem real e cobra o canal de notificação novamente; chame
`estimate_resend_cost()` antes quando o custo precisar ser conhecido.

### 5. O lado do signatário

Signatários agem com um **código de acesso de signatário** de uso único, não com a sua chave de API.
O SDK o envia no parâmetro de consulta documentado `signer-access-code` e nunca anexa as credenciais
do seu workspace a essas rotas.

```python
# O signatário abre o link e confirma o código recebido por e-mail ou WhatsApp.
client.signers.verify_code(signer_access_code, "123456")
client.signers.accept_terms(signer_access_code)

# Leia o que esse signatário pode ver.
view = client.assignments.get_for_signer(signer_access_code)
me = client.signers.get_self(signer_access_code)

# Confirme os dados de identidade e então submeta.
client.signers.confirm_data(
    document["id"],
    signer_access_code,
    {"full_name": "Signatário de Exemplo", "email": "signatario@example.com",
     "government_id": "39053344705"},
)
```

Um assignment virtual submete uma lista de itens vazia; um assignment collect submete uma entrada
por campo preenchido:

```python
client.assignments.sign(document["id"], assignment["id"], [], signer_access_code)

client.assignments.sign(
    document["id"],
    assignment["id"],
    [{"itemId": "item-1", "fieldId": "field-1", "pageId": "page-1", "value": "João Silva"}],
    signer_access_code,
)
```

Recusar é a alternativa mutuamente exclusiva a assinar:

```python
client.assignments.decline(
    document["id"], assignment["id"], "Não concordo com os termos.", signer_access_code
)
```

Um signatário com vários documentos pendentes pode agir em todos de uma vez — veja
[Documentos do signatário](#documentos-do-signatário).

### 6. Acompanhe o progresso

Webhooks são o canal confiável. Registre a assinatura única do workspace e então interprete as
entregas:

```python
client.webhooks.register({
    "url": "https://example.com/webhooks/assinafy",
    "email": "ops@example.com",
    "events": ["document_ready", "signer_signed_document", "signer_rejected_document"],
    "is_active": True,
})
```

```python
raw_body = request.get_data()

event = client.webhook_verifier.extract_event(raw_body)
event_type = client.webhook_verifier.get_event_type(event)   # ex.: "document_ready"
target = client.webhook_verifier.get_event_object(event)      # o documento afetado

if event_type == "document_ready":
    signed_pdf = client.documents.download(target["id"], "certificated")
```

Polling e a trilha de atividades também funcionam:

```python
document = client.documents.get(document["id"])
print(document["status"])
client.documents.activities(document["id"])
```

`activities()` devolve todos os eventos registrados do documento, cada um com um snapshot do
`payload` do evento e a `origin` da requisição (`ip`, `user-agent`).

### 7. Baixe o documento assinado

Quando todos os signatários concluem, o documento chega a `certificated` e seus artefatos ficam
disponíveis:

```python
document = client.documents.get(document["id"])
if document["status"] == "certificated":
    signed_pdf = client.documents.download(document["id"], "certificated")
    certificate_page = client.documents.download(document["id"], "certificate-page")
    everything = client.documents.download(document["id"], "bundle")
```

| Artefato | Conteúdo |
| --- | --- |
| `original` | O PDF enviado, como recebido |
| `certificated` | O documento assinado, com a certificação da plataforma |
| `certificate-page` | Apenas a página de certificação |
| `pades` | Assinaturas ICP-Brasil dos signatários + caixa de certificação — só existe em documentos que tiveram signatários por certificado digital |
| `bundle` | Zip com `original`, `certificated` e `certificate-page`, mais o `pades` quando houver |

Quem tiver o hash da assinatura verifica um documento sem nenhuma credencial:

```python
AssinafyClient().documents.verify(signature_hash)
```

Guarde os IDs de documento, signatário e assignment devolvidos. Apague apenas recursos descartáveis
que você criou, e na ordem inversa das dependências.

### Partindo de um template

Quando o layout do documento é fixo, crie-o a partir de um template e pule os estágios 2 e 4 — o
posicionamento de campos e os papéis já vivem no template:

```python
templates = client.templates.list({"search": "NDA"})
template = client.templates.get(templates["data"][0]["id"])
role_id = template["roles"][0]["id"]

client.documents.estimate_cost_from_template(
    template["id"],
    [{"role_id": role_id, "verification_method": "Email"}],
)

document = client.documents.create_from_template(
    template["id"],
    [{"role_id": role_id, "id": signer["id"], "verification_method": "Email"}],
    {"name": "NDA - João Silva", "message": "Por favor, assine."},
)
```

Signatários de template tomam uma entrada por papel do template, aceitam no máximo um método de
notificação cada, e seguem as mesmas regras de `step` contíguo dos assignments (papéis de cópia
ignoram `step`). `options` também aceita `expires_at`, `editor_fields`
(pares `{"field_id": ..., "value": ...}` gravados no documento gerado) e `tags` — nomes de tag que
não existem são criados automaticamente e mesclados às tags padrão do template.

## OAuth para aplicações de marketplace

Tudo acima pressupõe que você automatiza o **seu próprio** workspace com uma chave de API. Se você
está construindo um produto que **outras pessoas conectam ao workspace delas**, não peça a chave de
API dessas pessoas: execute o fluxo OAuth 2.1 de authorization code com PKCE e receba um token
limitado ao que elas aprovaram, para o único workspace que escolheram, e que elas podem desligar a
qualquer momento.

| | Chave de API | OAuth |
| --- | --- | --- |
| Age sobre | o **seu próprio** workspace | o workspace de **outra pessoa**, com a permissão dela |
| Pode fazer | tudo que a sua conta pode | somente o que o usuário aprovou |
| O usuário pode desligar | não | sim, a qualquer momento |

> OAuth é servido **apenas em produção** hoje. `https://sandbox.assinafy.com.br/v1/oauth/*`
> responde `404`.

O recurso é uma fábrica, e não um atributo, porque uma aplicação OAuth tem credenciais próprias:

```python
import os
from assinafy import AssinafyClient

# Um cliente sem credenciais basta para todo o fluxo até a troca do código.
oauth = AssinafyClient().oauth(
    os.environ["ASSINAFY_OAUTH_CLIENT_ID"],
    os.environ.get("ASSINAFY_OAUTH_CLIENT_SECRET"),  # só aplicações confidenciais
)
```

O SDK não guarda tokens, não mantém travas de renovação e não renova nada por conta própria. Essas
são decisões da sua aplicação, e as seções abaixo dizem exatamente onde elas caem.

### 1. Registre a aplicação

No app da Assinafy (<https://app.assinafy.com.br>) abra **Configurações → Aplicações OAuth → Nova
aplicação**. Você precisa ser proprietário do workspace que será dono da aplicação, e o plano dele
precisa incluir aplicações OAuth.

| Campo | O que colocar |
| --- | --- |
| Nome, Descrição, URL do logo | o que o usuário lê na tela de aprovação |
| URIs de redirecionamento | para onde o usuário volta, ex.: `https://meuapp.example.com/oauth/callback`. Deve ser `https://`, sem `#`, e é comparada **exatamente** — `…/callback` e `…/callback/` são diferentes. Registre uma por ambiente; em desenvolvimento local use um túnel HTTPS, porque `http://localhost` não é aceito |
| Permissões | o **máximo** que sua aplicação pedirá algum dia; você pode pedir menos na hora de conectar, nunca mais |
| Tipo | **Confidencial** se o código roda num servidor seu, **Pública** se roda no dispositivo do usuário. Não pode ser alterado depois |

Você recebe um `client_id` e, para aplicações confidenciais, um `client_secret` exibido uma única
vez. Guarde o segredo no cofre de segredos do seu servidor; nunca o publique em código de navegador,
em app mobile ou em repositório.

Os escopos:

| Escopo | Permite à sua aplicação |
| --- | --- |
| `documents:read` | ler documentos, seus signatários, assignments e atividades |
| `documents:write` | criar documentos e enviá-los para assinatura |
| `templates:read` / `templates:write` | ler / alterar templates |
| `account:read` | ler o perfil, o tema e o logo do workspace |
| `webhooks:write` | configurar e desativar a assinatura de webhooks do workspace |
| `openid`, `profile`, `email` | identificar o usuário e ler nome e e-mail |
| `offline_access` | receber um refresh token, para continuar funcionando com o usuário ausente |

Peça o mínimo: cada permissão é uma linha a mais que o usuário lê antes de decidir, e ele aprova
tudo ou nada. Cobrança, assinatura do plano, participação no workspace, gestão de credenciais e
administração **nunca** são alcançáveis por um token OAuth, quaisquer que sejam os escopos.

### 2. Leve o usuário até a Assinafy

`start_authorization()` gera um verificador PKCE e um `state` novos (e um `nonce` quando você pede
`openid`) e devolve a URL mais a transação que os passos seguintes precisam. Não faz requisição
HTTP.

```python
start = oauth.start_authorization(
    "https://meuapp.example.com/oauth/callback",
    ["documents:read", "documents:write", "offline_access"],
)

session["assinafy_oauth"] = start               # a sessão de servidor do usuário
return redirect(start["authorization_url"])     # navegação de página completa, não AJAX
```

```python
{
  "authorization_url": "https://auth.assinafy.com.br/oauth/authorize?response_type=code&...",
  "state": "<aleatório por tentativa>",
  "code_verifier": "<aleatório por tentativa>",
  "code_challenge": "<sha256 do verificador, em base64url>",
  "redirect_uri": "https://meuapp.example.com/oauth/callback",
  "issuer": "https://auth.assinafy.com.br",
  "resource": "https://api.assinafy.com.br",
}
```

Chame **uma vez por tentativa de conexão**: um verificador e um `state` novos a cada vez são toda a
proteção contra o material de uma tentativa ser reutilizado em outra. Guarde o retorno na sessão
autenticada do usuário, não em cookie nem na URL.

Se o `client_id` ou a `redirect_uri` estiverem errados, o usuário **não** é devolvido a você: o
servidor de autorização mostra o erro na própria página, porque redirecionar para um endereço não
verificado seria inseguro. Usuários presos numa página de erro da Assinafy normalmente significam
que um desses dois valores está errado.

### 3. Trate o callback e troque o código

`handle_callback()` é o passo crítico de segurança. Compara `state` e `iss` em tempo constante
**antes** de o código ser usado em qualquer lugar, e levanta o código de erro do RFC quando o
usuário recusou.

```python
from assinafy import ApiError, ValidationError

transaction = session.pop("assinafy_oauth")

try:
    code = oauth.handle_callback(request.args, transaction)
except ValidationError:
    return "Esta resposta não é nossa", 400      # state ou iss divergentes
except ApiError as err:
    if str(err) == "access_denied":
        return "Você recusou a conexão", 200
    raise

tokens = oauth.exchange_code(code, transaction)
```

```python
{
  "access_token": "<access-token>",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scope": "documents:read documents:write",
  "refresh_token": "<refresh-token>",   # só com offline_access
  "id_token": "<id-token assinado>",    # só com openid
}
```

O código é de uso único e expira **60 segundos** após a aprovação, então faça a troca no servidor e
imediatamente. Leia o `scope` devolvido em vez de supor que toda permissão pedida foi concedida;
`offline_access` é um sinal de requisição e nunca aparece ali.

Respostas de OAuth são JSON plano — são as únicas chamadas desta API que **não** vêm embrulhadas no
envelope `{status, message, data}`. Em caso de falha, `str(err)` é o código de erro do RFC
(`invalid_grant`, `invalid_client`, `invalid_target`, `unsupported_grant_type`) e
`err.response_data` carrega `error_description`, então ramifique pela mensagem.

### 4. Chame a API

Um token pertence ao **único** workspace que o usuário escolheu. Com um token OAuth, a listagem de
workspaces devolve exatamente aquele workspace, então guarde o ID dele junto dos tokens:

```python
api = AssinafyClient(token=tokens["access_token"])
workspace_id = api.accounts.list()[0]["id"]

documentos = api.documents.list({"per_page": 20}, account_id=workspace_id)
```

Envie sempre o token em `Authorization: Bearer`; como `X-Api-Key` ou na query string ele é recusado.
Chamar qualquer outro workspace devolve `403`, mesmo um ao qual o mesmo usuário pertence — este é o
erro de integração que mais vemos. Se o seu cliente usa vários workspaces, conecte cada um
separadamente e guarde tokens por workspace.

Uma permissão que falta responde `403` com um desafio que a nomeia:

```
WWW-Authenticate: Bearer error="insufficient_scope", scope="documents:write", ...
```

Trate isso como um pedido para reconectar com aquele escopo adicionado, não como algo a repetir. Um
`403` sem esse header tem outra causa: outro workspace, o papel do próprio usuário, ou uma área que
tokens OAuth nunca alcançam.

### 5. Renove e desconecte

Tokens de acesso duram **1 hora**. Com `offline_access` você os renova sem o usuário. Um refresh
token vale por **30 dias**, e cada renovação devolve um novo, válido por outros 30 dias: a conexão
só expira se a sua aplicação passar 30 dias sem renovar, e depois disso o usuário precisa
reconectar.

```python
tokens = oauth.refresh(refresh_token_guardado)
salvar(tokens["refresh_token"])    # antes de fazer qualquer outra coisa com a resposta
```

> **Toda renovação aposenta o token que usou.** Um refresh token reapresentado não pode ser
> distinguido de um roubado, então o servidor encerra a conexão inteira ao ver um: todos os tokens
> param de funcionar e o usuário precisa conectar de novo. Persista o novo refresh token antes de
> usar o access token, mantenha uma renovação por vez por conexão, e trate um timeout como "talvez
> tenha funcionado" — releia o que você guardou em vez de repetir com o token antigo.

Quando um usuário desconecta no seu produto, revogue em vez de apenas apagar a sua cópia. Revogar o
refresh token encerra a conexão inteira:

```python
oauth.revoke(carregar_refresh_token_salvo(), "refresh_token")  # o último token salvo, nunca uma cópia antiga
apagar_tokens_salvos()
```

O endpoint responde `200` para qualquer desfecho do token — revogado, já revogado, desconhecido,
malformado — então ele nunca pode ser usado para descobrir se um token existe, e sucesso não é prova
de que o token era real. Só falha de autenticação do cliente responde `401`. Os usuários também
podem revogar sua aplicação em **Aplicativos conectados**; trate o `401` resultante pedindo que
reconectem.

### Descoberta e OpenID Connect

Em vez de fixar endpoints no código, leia-os. `protected_resource_metadata()` (RFC 9728) descreve
esta API e nomeia o servidor de autorização dela; `authorization_server_metadata()` (RFC 8414)
descreve esse servidor. Os dois documentos ficam na raiz do respectivo host, acima de `/v1`, e são
buscados sem as credenciais do seu workspace.

```python
resource = oauth.protected_resource_metadata()
server = oauth.authorization_server_metadata(resource["authorization_servers"][0])

start = oauth.start_authorization(
    "https://meuapp.example.com/oauth/callback",
    ["documents:read", "openid", "email"],
    issuer=server["issuer"],
    authorization_endpoint=server["authorization_endpoint"],
)
```

Peça `openid` (mais `profile` e/ou `email`) para autenticar usuários. Valide o `id_token` com uma
biblioteca OpenID Connect mantida — RS256, chaves no `jwks_uri` do servidor, `iss` igual ao issuer,
`aud` igual ao seu `client_id`, `exp` no futuro, e `nonce` igual ao da sua transação. Para nome e
e-mail, leia as claims em vez do token:

```python
claims = oauth.userinfo(tokens["access_token"])
# {"sub": "...", "name": "Usuário de Exemplo", "email": "pessoa@example.com",
#  "email_verified": True}
```

`sub` é o identificador estável do usuário. `userinfo()` autentica como qualquer outra rota da API,
então, ao contrário dos endpoints de token, seus `401`/`403` chegam no envelope comum; o SDK remove
o `X-Api-Key` do cliente nessa chamada para que uma chave de workspace nunca responda pela
identidade errada.

Se o seu framework é o dono do material de sessão, as primitivas PKCE estão disponíveis
diretamente:

```python
verifier = OAuthResource.create_code_verifier()   # 43 caracteres, gramática do RFC 7636
challenge = OAuthResource.code_challenge(verifier)
state = OAuthResource.create_state()
```

### Checklist de OAuth

- Um verificador PKCE e um `state` novos em cada tentativa de conexão
- `state` e `iss` verificados na sua URI de redirecionamento — `handle_callback()` faz os dois
- `client_secret` só no seu servidor, nunca em código de navegador, app mobile ou repositório
- O novo refresh token salvo antes de usar, e uma renovação por vez por conexão
- `401` tratado: renove e, se falhar, peça ao usuário para reconectar
- O ID do workspace guardado por conexão, e o `scope` devolvido lido
- Toda URI de redirecionamento de produção registrada, `https://` e exata
- Somente as permissões necessárias
- Tokens revogados quando um usuário desconecta

Aplicações novas não são verificadas: a tela de aprovação avisa que a Assinafy não revisou o app, e
ele pode ser conectado a no máximo **25 workspaces**. Os endpoints de autorização e de token aceitam
**50 requisições por minuto por IP** — atingir esse limite normalmente significa um laço de
renovação.

## Referência por recurso

Todo método abaixo aparece em contexto acima; esta seção é o índice plano.

### Autenticação

```python
client.authentication.login("usuario@example.com", "senha")
client.authentication.social_login("google", "provider-token", True)
client.authentication.link_social_login("google", "provider-token")
client.authentication.create_api_key("senha")
client.authentication.get_api_key()
client.authentication.delete_api_key()
client.authentication.change_password("usuario@example.com", "antiga", "nova")
client.authentication.request_password_reset("usuario@example.com")
client.authentication.reset_password("usuario@example.com", "nova", token="reset-token")
```

### Contas

```python
accounts = client.accounts.list()
nova_conta = client.accounts.create("Workspace de Exemplo")
nova_id = nova_conta["id"]
nova_conta = client.accounts.update({"notification_sender_type": "Account"}, nova_id)
nova_conta = client.accounts.get(nova_id)
nova_conta = client.accounts.update({"name": "Workspace Atualizado"}, nova_id)
theme = client.accounts.theme(nova_id)
stats = client.accounts.stats("monthly", account_id=nova_id)
stats_diarias = client.accounts.stats("daily", "2026-08", account_id=nova_id)
client.accounts.upload_logo({"file_path": "./logo.png"}, nova_id)
logo_bytes = client.accounts.download_logo(nova_id)
client.accounts.delete_logo(nova_id)

# Apague apenas o workspace descartável criado acima.
client.accounts.delete(nova_id)
```

`delete()` atinge o ID de conta informado (ou o padrão do cliente) e torna `force` exclusivo de
palavra-chave, para que um ID posicional nunca seja confundido com a flag. Use `force=True` apenas
quando você quiser intencionalmente cancelar a assinatura paga ativa daquela conta como parte da
exclusão. Criar a conta primeiro e definir `notification_sender_type` com `update()` funciona em
todas as versões implantadas da API.

### Usuário autenticado

```python
user = client.users.me()
stats = client.users.stats("monthly")
preferences = client.users.notification_preferences()
preferences = client.users.update_notification_preferences({
    "DocumentCompleted": True,
    "SignerDeclined": True,
})
```

`update_notification_preferences` mescla um mapa parcial; chaves omitidas mantêm seus valores, e a
resposta é sempre o mapa completo de nove chaves.

### Documentos

```python
doc = client.documents.upload({"file_path": "./contrato.pdf"})
doc = client.documents.upload({"buffer": pdf_bytes, "file_name": "contrato.pdf"})

client.documents.statuses()
client.documents.list({"page": 1, "per_page": 20, "tags": "tag-id", "sort": "updated_at"})
client.documents.search({"search": "nda", "status": "metadata_ready"})  # leve, compacto
client.documents.get(doc["id"])
client.documents.rename(doc["id"], "Contrato.pdf")  # antes de a assinatura começar
client.documents.activities(doc["id"])
client.documents.wait_until_ready(doc["id"])
client.documents.download(doc["id"], "certificated")
client.documents.download(doc["id"], "pades")  # artefato de certificado ICP-Brasil
client.documents.thumbnail(doc["id"])
client.documents.download_page(doc["id"], page_id)
client.documents.verify(signature_hash)
client.documents.public_info(doc["id"])
# Escolha um formato; cada chamada envia um token real.
client.documents.send_token(doc["id"], email="signatario@example.com")
# Corpo legado alternativo:
# client.documents.send_token(doc["id"], "signatario@example.com", "email")
client.documents.list_tags(doc["id"])
client.documents.replace_tags(doc["id"], [tag_id_a, tag_id_b])
client.documents.append_tags(doc["id"], [tag_id_c])
client.documents.detach_tag(doc["id"], tag_id)
client.documents.delete(doc["id"])
```

`list()` filtra por `status`, `method`, `search`, `tags` (IDs separados por vírgula, retornando
documentos que carregam todas) e `sort` (`name` ou `updated_at`). `search()` é a versão compacta,
que devolve documentos sem os campos expandidos `assignment`/`pages`. A exclusão só é permitida
enquanto o documento está num status deletável.

### Templates

```python
templates = client.templates.list({"search": "NDA", "per_page": 20})
template = client.templates.get(template_id)

client.documents.create_from_template(
    template_id,
    [{"role_id": "role-id", "id": signer_id, "verification_method": "Email"}],
    {"name": "NDA - João Silva", "message": "Por favor, assine."},
)

client.documents.estimate_cost_from_template(
    template_id,
    [{"role_id": "role-id", "verification_method": "Email"}],
)
```

O OpenAPI publicado expõe apenas `list`. `get` é mantido porque a rota está implantada e responde na
API ao vivo, e o texto do schema publicado descreve uma resposta de template único que adiciona
`default_document_tags`.

### Tags

```python
tags = client.tags.list({"search": "contrato"})
tag = client.tags.create({"name": "Contratos", "color": "ff8800"})
client.tags.update(tag["id"], {"name": "Contratos de Venda"})
client.tags.update(tag["id"], {"color": None})  # remove a cor
client.tags.delete(tag["id"])
# Se a tag estiver vinculada, use isto no lugar da linha anterior:
# client.tags.delete(tag["id"], force=True)
```

### Signatários

```python
signer = client.signers.create({
    "full_name": "João Silva",
    "email": "joao@example.com",
})

client.signers.create({
    "full_name": "Maria Souza",
    "whatsapp_phone_number": "+5548999990000",
})

client.signers.get(signer["id"])
client.signers.list({"search": "joão", "per_page": 50})
client.signers.update(signer["id"], {"full_name": "João P. Silva"})
client.signers.find_by_email("joao@example.com")
client.signers.delete(signer["id"])
```

`create()` aceita `full_name`, `email` e `whatsapp_phone_number`. `government_id` (o CPF ou CNPJ que
o certificado digital exige) só existe em `update()`, então crie o signatário e depois complete o
documento dele.

Endpoints por código de acesso do signatário:

```python
client.signers.get_self(signer_access_code)
client.signers.accept_terms(signer_access_code)
client.signers.verify_code(signer_access_code, "123456")
# verify_email(...) permanece como alias retrocompatível.
client.signers.confirm_data(
    document_id,
    signer_access_code,
    {"full_name": "João Silva", "email": "joao@example.com",
     "government_id": "39053344705"},
)
client.signers.upload_signature(signer_access_code, png_bytes, "signature")
# Alternativa: client.signers.upload_signature(signer_access_code, png_bytes, reuse=True)
client.signers.download_signature(signer_access_code, "signature")
```

`update()` não pode alterar um canal já verificado para um documento em curso; a API garante isso no
servidor.

### Assignments

```python
client.assignments.list({"page": 1, "per_page": 20})
client.assignments.estimate_cost(document_id, {"signers": [{"verification_method": "Email"}]})
client.assignments.create(document_id, {"method": "virtual", "signers": [...]})
client.assignments.reset_expiration(document_id, assignment_id, "2031-01-31T00:00:00Z")
client.assignments.estimate_resend_cost(document_id, assignment_id, signer_id)
client.assignments.resend_notification(document_id, assignment_id, signer_id)
client.assignments.whatsapp_notifications(document_id, assignment_id)

# Voltados ao signatário:
client.assignments.get_for_signer(signer_access_code)
client.assignments.sign(document_id, assignment_id, [], signer_access_code)
client.assignments.decline(document_id, assignment_id, "Não concordo.", signer_access_code)
```

`list()` é escopado pela API à conta atual da credencial autenticada. O SDK encaminha um parâmetro
de contexto `accountId`, mas passar um `account_id` diferente **não** reescopa este endpoint — use
uma credencial que pertença àquele workspace.

### OAuth

```python
oauth = client.oauth("client-id", "client-secret")

start = oauth.start_authorization(
    "https://meuapp.example.com/oauth/callback",
    ["documents:read", "documents:write", "offline_access"],
)
code = oauth.handle_callback(callback_query, start)
tokens = oauth.exchange_code(code, start)
tokens = oauth.refresh(tokens["refresh_token"])
claims = oauth.userinfo(tokens["access_token"])
oauth.revoke(tokens["refresh_token"], "refresh_token")

oauth.protected_resource_metadata()
oauth.authorization_server_metadata()

# Primitivas PKCE estáticas, para frameworks que são donos do material de sessão.
OAuthResource.create_code_verifier()
OAuthResource.create_state()
OAuthResource.code_challenge(verifier)
```

`start_authorization()` e `handle_callback()` não fazem requisição HTTP. Veja
[OAuth para aplicações de marketplace](#oauth-para-aplicações-de-marketplace) para o fluxo completo.

### Documentos do signatário

```python
client.signer_documents.current(signer_id, signer_access_code)
client.signer_documents.list(signer_id, signer_access_code, {"page": 1, "per_page": 20})
client.signer_documents.search(signer_id, signer_access_code, "contrato")  # leve
client.signer_documents.sign_multiple(["doc-1", "doc-2"], signer_access_code)
# Alternativa mutuamente exclusiva:
# client.signer_documents.decline_multiple(["doc-1"], "Termos desfavoráveis.", signer_access_code)
client.signer_documents.download(signer_id, document_id, artifact_name="original")
```

A rota de download é pública. O argumento opcional `signer_access_code` existe para implantações
que o exijam.

### Definições de campo

```python
field = client.fields.create({"type": "text", "name": "CPF"})
client.fields.list({"include_standard": True})
client.fields.get(field["id"])
client.fields.update(field["id"], {"name": "CPF atualizado"})
client.fields.update(field["id"], {"regex": None})  # remove o regex
client.fields.validate(field["id"], "390.533.447-05", signer_access_code=signer_access_code)
client.fields.validate_multiple(
    [{"field_id": field["id"], "value": "390.533.447-05"}],
    signer_access_code=signer_access_code,
)
client.fields.list_types()
client.fields.delete(field["id"])
```

`create()` recebe `type` (um dos valores de `list_types()`) e `name`, opcionalmente `regex` e
`is_required`. `is_read_only` / `is_visible` são campos de resposta controlados pelo servidor, não
entrada de criação.

### Webhooks

```python
client.webhooks.get()
client.webhooks.list_event_types()
client.webhooks.list_dispatches({"delivered": False, "page": 1, "per_page": 20})

# Chamadas mutantes afetam a assinatura única do workspace ou reenviam um evento
# existente. Guarde e restaure a assinatura ao redor de mudanças de teste.
# client.webhooks.register({
#     "url": "https://example.com/webhooks/assinafy",
#     "email": "admin@example.com",
#     "events": ["document_ready", "signer_signed_document"],
#     "is_active": True,
# })
# client.webhooks.inactivate()
# client.webhooks.retry_dispatch(dispatch_id)
```

Um workspace tem uma única assinatura de webhook. Não existe endpoint `DELETE` documentado — chame
`inactivate()` para parar a entrega (preserva a URL e os eventos configurados) e `register()` de
novo para reativar. Como a assinatura é única, `register()` preenche um `events` ou `is_active`
omitido a partir da assinatura *atual*, para que uma chamada parcial (trocar só a `url`, por
exemplo) não reative silenciosamente uma assinatura inativada nem colapse uma lista de eventos
customizada. Passe `events=[]` explicitamente para realmente limpar todos os eventos.

**Interpretando payloads.** Todo corpo de webhook compartilha o envelope documentado: `id`, `event`,
`message`, `payload` (parâmetros do evento), `origin`, `created_at`, `subject` (a entidade que
agiu), `object` (a entidade sobre a qual se agiu) e `account_id`.

```python
raw_body = request.get_data()

event = client.webhook_verifier.extract_event(raw_body)
event_type = client.webhook_verifier.get_event_type(event)      # ex.: "document_ready"
params = client.webhook_verifier.get_event_payload(event)        # parâmetros do evento
subject = client.webhook_verifier.get_event_subject(event)       # autor (+ "type")
target = client.webhook_verifier.get_event_object(event)         # alvo (+ "type")
# get_event_data(event) é um alias retrocompatível de get_event_object(event)
```

**Verificação de assinatura.** O Contrato de Entrega documentado especifica o método HTTP, o
`Content-Type`, as retentativas e o comportamento do circuit breaker, mas **não define nenhum header
de assinatura nem esquema de segredo compartilhado**. `verify()` existe apenas para contas que
combinaram separadamente um esquema HMAC-SHA256 com a Assinafy:

```python
signature = request.headers.get("X-Assinafy-Signature", "")
if not client.webhook_verifier.verify(raw_body, signature):
    return "Assinatura inválida", 401
```

## Parâmetros de consulta

O SDK aceita apelidos Pythônicos para os parâmetros de consulta hifenizados documentados. Por
exemplo, `per_page` é enviado como `per-page`, e `signer_access_code` como `signer-access-code`.
Valores `None` são descartados em vez de enviados como parâmetros vazios.

## Formatos de resposta

Endpoints JSON normalmente devolvem `{"status": 200, "message": "", "data": ...}`; o SDK devolve
`data`. As cinco chamadas de OAuth são a exceção documentada: RFC 6749, RFC 8414 e OpenID Connect
todos exigem um corpo plano, então `exchange_code`, `refresh`, `userinfo` e os dois métodos de
descoberta devolvem JSON de nível superior, e `revoke` devolve `None`.

Operações sem dados devolvem `None` ou preservam o pequeno envelope `{"status", "message"}` por
retrocompatibilidade, como está dito na docstring de cada método. Métodos binários devolvem `bytes`;
métodos paginados devolvem
`{"data": [...], "meta": {"current_page", "per_page", "total", "last_page"}}`, usando os headers de
paginação da API.

Os formatos estáveis de nível superior de cada recurso são:

```json
{
  "Account": {
    "resource": "account", "id": "account-id", "name": "Acme Inc.",
    "primary_color": "aabbcc", "secondary_color": "112233",
    "notification_sender_type": "User", "roles": ["owner"],
    "is_delete_allowed": true, "created_at": "2026-06-03T03:54:16Z"
  },
  "User": {
    "id": "user-id", "name": "Usuário de Exemplo", "email": "usuario@example.com",
    "telephone": null, "government_id": null, "is_email_verified": true,
    "has_accepted_terms": true, "created_at": "2026-06-03T03:54:16Z",
    "to_be_deleted_at": null
  },
  "Signer": {
    "resource": "signer", "id": "signer-id", "full_name": "Signatário de Exemplo",
    "email": "signatario@example.com", "whatsapp_phone_number": null,
    "has_accepted_terms": false
  },
  "Document": {
    "resource": "document", "id": "document-id", "account_id": "account-id",
    "template_id": null, "name": "contrato.pdf", "status": "metadata_ready",
    "artifacts": {"original": "https://api.example/document/original"},
    "is_closed": false, "signing_url": "https://app.example/sign/document-id",
    "decline_reason": null, "declined_by": null, "tags": [],
    "assignment": null, "pages": [], "created_at": "2026-06-03T03:54:16Z",
    "updated_at": "2026-06-03T03:54:17Z"
  },
  "Assignment": {
    "resource": "assignment", "id": "assignment-id",
    "sender_email": "remetente@example.com", "method": "virtual",
    "expires_at": null, "message": null,
    "signers": [{
      "resource": "signer", "id": "signer-id", "full_name": "Signatário de Exemplo",
      "email": "signatario@example.com", "whatsapp_phone_number": null,
      "has_accepted_terms": false, "verification_method": "Email",
      "notification_methods": ["Email"], "step": 1, "notified": true,
      "completed": false, "notification_history": [{
        "event": "signature_request", "status": "sent", "error_code": null,
        "error_message": null, "sent_at": "2026-08-26T12:00:00Z",
        "failed_at": null
      }]
    }],
    "copy_receivers": [],
    "items": [{
      "id": "item-id",
      "page": {"id": "page-id", "number": 1, "height": 2100,
               "width": 1275, "download_url": "https://api.example/page"},
      "signer": {"id": "signer-id", "full_name": "Signatário de Exemplo",
                 "email": "signatario@example.com"},
      "field": {"id": "field-id", "name": "Assinatura", "type": "signature"},
      "display_settings": {"left": 69, "top": 282, "width": 421,
                           "height": 45.86, "fontFamily": "Arial",
                           "fontSize": 18, "backgroundColor": "#D5EBFF"},
      "value": null, "completed": false
    }],
    "summary": {"signer_count": 1, "completed_count": 0,
                "signers": [{"id": "signer-id", "full_name": "Signatário de Exemplo",
                             "email": "signatario@example.com", "completed": false}]},
    "signing_urls": [{"signer_id": "signer-id",
                      "url": "https://api.example/sign/document-id"}]
  },
  "CostEstimate": {
    "documents": 1, "credits": 0.45, "needs_extra_document": false,
    "extra_document_cost": 0, "total_credits": 0.45,
    "breakdown": [{"code": "NotificationWhatsapp",
                   "name": "Whatsapp Notification", "cost": 0.45,
                   "quantity": 1, "unit_cost": 0.45}],
    "document_balance": 10, "credit_balance": 0,
    "has_sufficient_resources": true, "blocking_reason": null, "message": null
  },
  "Field": {
    "resource": "field", "id": "field-id", "name": "CPF", "type": "text",
    "regex": null, "is_pre_defined": false, "is_active": true,
    "is_required": true, "is_standard": false, "is_read_only": false,
    "is_visible": true
  },
  "Tag": {
    "resource": "tag", "id": "tag-id", "name": "Contratos", "color": null,
    "created_at": "2026-06-03T03:54:16Z",
    "updated_at": "2026-06-03T03:54:17Z"
  },
  "WebhookSubscription": {
    "events": ["document_ready"], "is_active": true,
    "url": "https://example.com/webhooks/assinafy", "email": "ops@example.com",
    "updated_at": "2026-06-03T03:54:17Z"
  }
}
```

Valores do recurso de campo são devolvidos literalmente. O valor documentado é `"field"`;
`"field_definition"` também é aceito.

Contratos de template, preferências de notificação, KPIs, verificação, entregas de webhook e
contratos específicos de operação estão documentados junto aos métodos públicos correspondentes;
métodos que devolvem recursos compartilhados referenciam os formatos canônicos acima. O SDK preserva
campos extras do servidor, de modo que mudanças aditivas na API permanecem utilizáveis.

## Erros

Falhas de validação, de transporte, de HTTP e de formato de resposta levantam uma subclasse de
`AssinafyError`, então um único `except AssinafyError` captura todos os modos de falha documentados.

```python
from assinafy import ApiError, AssinafyError, NetworkError, ValidationError

try:
    client.documents.upload({"file_path": "./contrato.pdf"})
except ValidationError as err:      # rejeitado antes de a requisição ser enviada
    print("Validação falhou:", err.errors)
except ApiError as err:             # a API devolveu uma resposta não-2xx
    print(f"Erro da API {err.status_code}:", err.response_data)
except NetworkError as err:         # nenhuma resposta chegou (DNS, TLS, timeout)
    print("Erro de rede:", err)
except AssinafyError as err:        # formato de resposta inesperado, etc.
    print("Erro do SDK:", err, err.context)
```

## Ambientes

| | |
| --- | --- |
| Produção | `https://api.assinafy.com.br/v1` |
| Sandbox | `https://sandbox.assinafy.com.br/v1` |

O sandbox é gratuito e espelha a produção para testar a integração de ponta a ponta — com duas
exceções: as rotas de OAuth existem apenas em produção, e o certificado digital depende de um
certificado ICP-Brasil real no dispositivo do signatário.

## Desenvolvimento

```bash
python -m pip install -e ".[dev]"
python -m pytest --cov=assinafy --cov-branch --cov-fail-under=90 --cov-report=term-missing
python -m mypy src scripts/live_smoke.py
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
```

### Teste de fumaça ao vivo

Para cobertura não mutante, segura para CI (nenhum e-mail de teste necessário):

```bash
ASSINAFY_API_KEY=... \
ASSINAFY_ACCOUNT_ID=... \
ASSINAFY_BASE_URL=https://sandbox.assinafy.com.br/v1 \
ASSINAFY_READ_ONLY=1 \
python scripts/live_smoke.py
```

Para o fluxo de escrita descartável:

```bash
ASSINAFY_API_KEY=... \
ASSINAFY_ACCOUNT_ID=... \
ASSINAFY_BASE_URL=https://sandbox.assinafy.com.br/v1 \
ASSINAFY_TEST_EMAILS=primeiro@example.com,segundo@example.com \
ASSINAFY_SEND_TEST_NOTIFICATIONS=1 \
ASSINAFY_TEST_ACCOUNT_LIFECYCLE=1 \
ASSINAFY_TEST_USER_PREFERENCES=1 \
python scripts/live_smoke.py
```

O script recusa produção e URLs base ausentes, e nunca imprime um payload ou o valor de uma
variável de ambiente. Ele confere os endpoints de leitura, o CRUD de signatário/tag/campo (incluindo
remover o regex de um campo), a busca e a estimativa de template, o upload de documento, a marcação
por tags, o polling de `wait_until_ready`, a estimativa de custo e a limpeza de ponta a ponta. Todo
ID de recurso devolvido com sucesso é capturado e sua limpeza é tentada num bloco `finally`. A
mutação de webhook é ignorada a menos que um endpoint de teste explícito seja fornecido; quando
habilitada, a assinatura única anterior do workspace é restaurada. O opt-in de notificações envia
e-mails reais no sandbox e pode consumir créditos; omita-o para cobertura apenas de CRUD. As
mutações de conta e de preferências de usuário são opt-ins separados e são restauradas no `finally`.

### Checklist de release

1. Atualize `src/assinafy/_version.py` e acrescente as notas de release voltadas ao usuário em
   `CHANGELOG.md`.
2. Execute os comandos de desenvolvimento acima, instale as ferramentas de release com
   `python -m pip install build twine`, e então rode `python -m build` e
   `python -m twine check dist/*`.
3. Publique no GitLab e confirme que o branch e o resultado do CI chegaram ao espelho no GitHub.
4. Crie e publique uma tag anotada `v<versão>` igual a `__version__`.
5. Aprove o ambiente protegido `pypi` e confira a proveniência do Trusted Publishing após o
   release.

## Documentação

- **[README.en.md](README.en.md)** — este mesmo documento, em inglês
- [Documentação da API](https://api.assinafy.com.br/v1/docs)

## Licença

Distribuído sob a licença [MIT](LICENSE).
