# SDK Python da Assinafy

*Português · [Read in English](README.en.md)*

SDK oficial em Python para a [API Assinafy](https://api.assinafy.com.br/v1/docs) — plataforma
brasileira de assinatura eletrônica de documentos.

O SDK é síncrono, construído sobre `httpx`, e cobre as 89 operações publicadas hoje pela Assinafy:
contas, usuários, autenticação, documentos, signatários, documentos do signatário, assignments,
definições de campo, templates, tags e webhooks. Todo método público nomeia o verbo e o caminho que
chama, e documenta o corpo da requisição e a resposta já desembrulhada.

> **Referência completa em inglês.** Este documento cobre instalação, autenticação e os fluxos
> principais. O manual de referência por recurso está em **[README.en.md](README.en.md)**.

## Requisitos

- Python 3.10+
- `httpx` (instalado automaticamente)

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

O SDK **retém** as duas credenciais nas rotas cuja segurança publicada é pública ou apenas por código
de acesso do signatário — assim uma chave de API nunca é enviada a um endpoint que não a espera. Toda
requisição de produção e sandbox usa `User-Agent: Assinafy-Python-SDK/v<versão-do-pacote>`.

Clientes sem autenticação são permitidos, para endpoints públicos e por código de acesso:

```python
public_client = AssinafyClient()
session = public_client.authentication.login("usuario@exemplo.com.br", "senha")
```

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

`http://` em texto puro é rejeitado para qualquer host que não seja loopback: `login`, `social_login`,
`change_password`, `reset_password` e `create_api_key` enviam segredos no corpo da requisição mesmo
quando o cliente não tem `api_key` nem `token`, então a interface de loopback é o único lugar onde
texto puro é seguro. Aponte servidores locais e de mock para `localhost`/`127.0.0.1`.

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
            {"full_name": "João Silva", "email": "joao@exemplo.com.br"},
            {"full_name": "Maria Souza", "email": "maria@exemplo.com.br"},
        ],
        message="Por favor, assine este contrato",
    )

    print(resultado["document"]["id"])
```

Ele encadeia três chamadas — upload, criação de cada signatário e criação do assignment — e **não é
transacional**: uma falha no meio do caminho não desfaz o que já deu certo. Aceita também
`wait_timeout` / `wait_poll_interval` para sobrescrever o polling padrão de prontidão do documento.

Signatários só com telefone usam verificação e notificação por WhatsApp, o que exige disponibilidade
na conta e consome créditos — use `assignments.estimate_cost()` quando o custo precisar ser conhecido
antes do envio.

Quando você precisar de IDs explícitos, controle de custo ou limpeza, conduza o mesmo ciclo de vida
pelos recursos individuais.

## Métodos de verificação do signatário

Definidos por signatário em `verification_method` ao criar o assignment. O método de verificação e o
de notificação são **acoplados**: envie um, os dois ou nenhum — o lado que faltar é inferido. Sem
nenhum dos dois, ambos assumem `Email`.

| Método | Como funciona | Custo por signatário |
| --- | --- | --- |
| `Email` *(padrão)* | Código de uso único (OTP) por e-mail, exigido antes de assinar | Gratuito |
| `Whatsapp` | Código de uso único (OTP) por WhatsApp | Verificação gratuita; notificação 0,45 crédito, só em planos pagos |
| `DigitalCertificate` | O signatário assina com o **próprio certificado ICP-Brasil (A1/A3)**, pela extensão de navegador Web PKI, gerando uma assinatura **PAdES qualificada** | 2 créditos |

Combinações permitidas: `Email` → notifica por `Email`; `Whatsapp` → notifica por `Whatsapp`;
`DigitalCertificate` → notifica por `Email` **ou** `Whatsapp`. Apenas um método de notificação por
signatário.

### Certificado digital ICP-Brasil

Exige o recurso **Certificado Digital** na conta (planos Standard e Pro), CPF ou CNPJ em
`government_id` do signatário, e exatamente **um signatário por certificado naquele passo**. Um CPF
exige o certificado daquela pessoa (e-CPF, ou e-CNPJ que a nomeie como representante legal); um CNPJ
exige um e-CNPJ da empresa.

```python
signatario = client.signers.update(signer_id, {"government_id": "390.533.447-05"})

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

Antes de abrir o assignment, o signatário precisa confirmar os dados de identidade e aceitar os
termos (`confirm_data(..., has_accepted_terms=True)` ou `accept_terms()`).

O endpoint comum de assinatura **rejeita** signatários por certificado: a assinatura deles é
produzida por um handshake de dois passos com a extensão Web PKI.

```
POST /v1/signers/certificate/start     → data.token   (token da operação Web PKI)
        ↓  o navegador assina o token com o certificado do signatário
POST /v1/signers/certificate/complete  → data.signerName
```

> Essas duas rotas são extensões implantadas **somente em produção**: o sandbox não as expõe e elas
> não constam do documento OpenAPI publicado.

Concluído o fluxo, baixar o artefato `pades` devolve a assinatura PAdES qualificada.

## Trilha de atividades e artefatos

`client.documents.activities(document_id)` devolve todos os eventos registrados do documento, cada um
com um snapshot do `payload` do evento e a `origin` da requisição (`ip`, `user-agent`).

Ao baixar um documento, os artefatos disponíveis são:

| Artefato | Conteúdo |
| --- | --- |
| `original` | O PDF enviado, como recebido |
| `certificated` | O documento assinado, com a certificação da plataforma |
| `certificate-page` | Apenas a página de certificação |
| `pades` | Assinaturas ICP-Brasil dos signatários + caixa de certificação — só existe em documentos que tiveram signatários por certificado digital |
| `bundle` | Zip com `original`, `certificated` e `certificate-page`, mais o `pades` quando houver |

A verificação pública confere um documento assinado pelo hash da assinatura, sem autenticação.

## Recursos do cliente

```
client.accounts          client.documents      client.templates   client.tags
client.signers           client.assignments    client.fields      client.webhooks
client.signer_documents  client.users          client.authentication
```

## Ambientes

| | |
| --- | --- |
| Produção | `https://api.assinafy.com.br/v1` |
| Sandbox | `https://sandbox.assinafy.com.br/v1` |

O sandbox é gratuito e espelha a produção para testar a integração de ponta a ponta — com a exceção
das rotas de certificado digital, que existem apenas em produção.

## Documentação

- **[README.en.md](README.en.md)** — referência completa por recurso, em inglês
- [Documentação da API](https://api.assinafy.com.br/v1/docs)

## Licença

Distribuído sob a licença [MIT](LICENSE).
