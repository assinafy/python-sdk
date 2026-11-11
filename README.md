# SDK Python da Assinafy

*Português · [Read in English](README.en.md)*

Cliente Python síncrono para a [API Assinafy](https://api.assinafy.com.br/v1/docs), com suporte a documentos, signatários, assignments, templates, campos, contratos, webhooks, autenticação e OAuth 2.1 com PKCE.

## Instalação

Requer Python 3.10+ e TLS 1.2 ou superior; prefira Python 3.15 em produção. Python não tem edição LTS; 3.10 permanece por compatibilidade.

```bash
pip install assinafy
```

## Cliente e autenticação

Use uma chave de API para o seu workspace, um token para uma sessão de usuário ou OAuth para acessar o workspace conectado por outra pessoa.

```python
import os
from assinafy import AssinafyClient

client = AssinafyClient(
    api_key=os.environ["ASSINAFY_API_KEY"],
    account_id=os.environ["ASSINAFY_ACCOUNT_ID"],
)
```

| Modo | Enviado como | Uso |
| --- | --- | --- |
| Chave de API | `X-Api-Key` | seu próprio workspace |
| Token de acesso | `Authorization: Bearer` | sessão obtida por `authentication.login()` |
| Código do signatário | `signer-access-code` na query | ações da pessoa que assina |
| OAuth 2.1 + PKCE | `Authorization: Bearer` | aplicativos de marketplace |

O cliente remove credenciais de workspace das rotas públicas e de signatário; no OAuth userinfo, remove a chave de API e mantém o bearer explícito. Use `https://sandbox.assinafy.com.br/v1` em `base_url` para o sandbox. URLs não loopback devem usar HTTPS. O cliente compartilha um pool de conexões; use `with` ou chame `close()`.

## Fluxo completo de assinatura

O atalho `upload_and_request_signatures()` envia o PDF, cria signatários, espera o processamento e solicita assinaturas virtuais. As etapas não são transacionais: em caso de falha, `AssinafyError.context` contém os IDs já criados. Para controlar métodos, respostas e custos, use os recursos:

```python
document = client.documents.upload({"file_path": "./contrato.pdf"})
document = client.documents.wait_until_ready(document["id"])
signer = client.signers.create({
    "full_name": "Pessoa Exemplo",
    "email": "signer@example.com",
})
request = {
    "method": "virtual",
    "message": "Por favor, assine o documento.",
    "signers": [{
        "id": signer["id"],
        "verification_method": "Email",
        "notification_methods": ["Email"],
        "step": 1,
    }],
}
estimate = client.assignments.estimate_cost(document["id"], {
    "method": "virtual", "signers": [{"verification_method": "Email"}],
})
if not estimate["has_sufficient_resources"]:
    raise RuntimeError("Saldo insuficiente para solicitar assinaturas")
request["max_total_credits"] = estimate["total_credits"]
assignment = client.assignments.create(document["id"], request)

status = client.documents.get(document["id"])
if status["status"] == "certificated":
    pdf = client.documents.download(document["id"], "certificated")
```

### Verificação e notificação

| `verification_method` | Notificação | Requisitos |
| --- | --- | --- |
| `Email` | `Email` | e-mail do signatário |
| `Whatsapp` | `Whatsapp` | telefone WhatsApp e disponibilidade no plano |
| `IdDocumentFaceMatchBasic` | `Email` ou `Whatsapp` | CPF, recurso biométrico e consentimento explícito |
| `DigitalCertificate` | `Email` ou `Whatsapp` | CPF/CNPJ, recurso de certificado e assignment virtual |

Sem métodos informados, a API usa e-mail. Certificado digital aceita A1/A3 ICP-Brasil, exige que o signatário fique sozinho no passo e produz o artefato PAdES. Biometria usa uma captura hospedada; a URL retornada é uma credencial e não deve ser registrada.

No fluxo biométrico, consulte e inicie a captura somente após obter consentimento:

```python
state = client.signers.identity_verification(signer_access_code)
capture = client.signers.start_identity_verification(signer_access_code, consent=True)
```

O workspace consulta a evidência com `assignments.identity_verification()` e conclui a análise com `assignments.review_identity_verification()`.

As ações de e-mail/WhatsApp/biometria usam apenas o código de acesso; A1/A3 conclui a assinatura no fluxo hospedado da Assinafy:

```python
public_client = AssinafyClient()
public_client.signers.verify_code(signer_access_code, verification_code)
view = public_client.assignments.get_for_signer(signer_access_code)
public_client.signers.confirm_data(document["id"], signer_access_code, {
    "email": "signer@example.com", "has_accepted_terms": True,
})
public_client.signers.accept_terms(signer_access_code)
signed = public_client.assignments.sign(
    document["id"], assignment["id"], [], signer_access_code
)
```

## Templates e contratos

Crie documentos a partir de um template e espere o processamento antes de usar as páginas:

```python
document = client.documents.create_from_template(
    template_id,
    [{"role_id": "role-id", "email": "signer@example.com", "name": "Pessoa Exemplo"}],
    {"name": "Contrato de exemplo"},
)
document = client.documents.wait_until_ready(document["id"])
```

Use `idempotency_key=` para recuperar uma criação de template após resposta perdida. Templates criam assignments de forma assíncrona: aguarde `assignment_created` antes de acessá-los; `wait_until_ready()` espera apenas a renderização.

`client.contracts` lista, lê e atualiza termos, relaciona instrumentos, renova e encerra contratos. Escritas aceitam `updated_at` para impedir a sobrescrita de uma versão mais recente.

## Envelopes e assinatura dentro do aplicativo

Como alternativa aos assignments individuais, envie até 20 documentos processados e ainda sem assignment aos mesmos signatários; cada documento mantém sua assinatura, status e certificado:

```python
payload = {"name": "Contrato e anexos", "signers": [{"id": signer["id"]}],
           "documents": [{"id": unassigned_document_id, "signer_ids": [signer["id"]]}]}
cost = client.envelopes.estimate_cost(payload)
payload["max_total_credits"] = cost["total_credits"]
envelope = client.envelopes.create(payload, idempotency_key="pedido-exemplo-001")
```

Use uma chave nova por envelope; reutilize-a somente para recuperar a mesma criação. O recurso também lista, atualiza, cancela, remove/adiciona documentos, reenvia convites e baixa ZIPs. Certificado digital fica sozinho em cada documento; envelopes não aceitam passos de assinatura.

Para incorporar e-mail/WhatsApp, configure `accounts.add_embed_origin("https://app.example.com")`, adicione `"embedded": True` à entrada do signatário no assignment e use `assignments.create_embed_session(document_id, assignment_id, signer_id)`. Carregue `url` no iframe em até cinco minutos; cada abertura exige uma sessão nova. `embed.exchange()` pertence à página incorporada e consome o token. Origens e sessões exigem o recurso Embed; nunca exponha a chave do workspace ao navegador.

## OAuth 2.1 para marketplace

Registre a aplicação e os redirect URIs na Assinafy. Guarde cada transação no servidor e consuma-a uma única vez:

```python
oauth = client.oauth(
    os.environ["ASSINAFY_CLIENT_ID"],
    os.environ.get("ASSINAFY_CLIENT_SECRET"),
)
transaction = oauth.start_authorization(
    "https://app.example.com/oauth/callback",
    ["documents:read", "documents:write", "offline_access"],
)
# Salve transaction na sessão autenticada e redirecione para authorization_url.
authorization_url = transaction["authorization_url"]

# No callback, use a query já analisada pelo framework.
code = oauth.handle_callback(callback_query, transaction)
tokens = oauth.exchange_code(code, transaction)
connected = AssinafyClient(token=tokens["access_token"])
```

PKCE S256, `state` e `iss` são obrigatórios. O código expira rapidamente e é de uso único. Cada refresh token também é de uso único; substitua-o atomicamente pelo novo valor retornado:

```python
new_tokens = oauth.refresh(tokens["refresh_token"])
oauth.revoke(new_tokens["refresh_token"], token_type_hint="refresh_token")
```

Não repita automaticamente trocas ou renovações após erro de rede: a requisição pode ter sido aceita. Segredos, tokens, códigos e a transação OAuth devem permanecer no servidor.

## Webhooks

Configure `webhook_secret` e valide o corpo bruto antes de analisar o JSON. Depois de validar, deduplique por `webhook-id` dentro da janela de assinatura.

```python
client = AssinafyClient(webhook_secret=os.environ["ASSINAFY_WEBHOOK_SECRET"])
if not client.webhook_verifier.verify_delivery(raw_body, request_headers):
    raise ValueError("Assinatura de webhook inválida")
event = client.webhook_verifier.extract_event(raw_body)
```

## Respostas, erros e referência

Objetos e listas são devolvidos sem o envelope `{status, message, data}`. Listas paginadas têm `{"data": [...], "meta": {...}}`; downloads retornam `bytes`. O SDK nunca repete uma requisição automaticamente.

Capture `AssinafyError`; use `ApiError.status_code`, `response_data`, `retry_after` e os campos `rate_limit_*` para erros HTTP e limites. `ValidationError` ocorre antes de I/O e `NetworkError` representa falhas de transporte.

Veja [todos os recursos e payloads](README.en.md#resource-reference), incluindo uso do workspace, políticas de notificação, preferências push, cópias certificadas e rotação de webhook com sobreposição de 24 horas. Cada método público documenta verbo, rota, corpo e resposta. Recursos disponíveis em `AssinafyClient`: `accounts`, `assignments`, `authentication`, `contracts`, `documents`, `embed`, `envelopes`, `fields`, `signer_documents`, `signers`, `tags`, `templates`, `users`, `webhooks` e a fábrica `oauth()`.

## Desenvolvimento

```bash
ruff check src tests scripts
ruff format --check src tests scripts
mypy src scripts/live_smoke.py
pytest --cov=assinafy --cov-branch --cov-fail-under=90
```

Licença MIT. Consulte a [documentação oficial da API](https://api.assinafy.com.br/v1/docs) para scopes, limites, catálogos e schemas atuais.
