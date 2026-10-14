# Security Policy

## Supported versions

Chronicle is pre-1.0. Security fixes are applied to the latest released version on the `main`
branch.

## Reporting a vulnerability

Please report security issues **privately**. Do not open a public issue.

- Preferred: open a private
  [GitHub Security Advisory](https://github.com/theagentplane/chronicle/security/advisories/new)
  for this repository.

We aim to acknowledge reports within 3 business days and to share a remediation plan after triage.
Please give us a reasonable window to fix the issue before public disclosure.

## Data-handling posture (read this before recording production traffic)

Chronicle captures what your agents did. By design an envelope can contain the most sensitive data
in your system:

- the **full prompt** and the model's response (including tool-call arguments),
- **tool inputs and outputs**, and
- the **raw** input and output exactly as they crossed the boundary.

Chronicle sends these to the control plane you configure. There is no local copy, but the control
plane stores them for its retention period, so treat it as a store of production data.

**What Chronicle does for you**

1. **Redaction before send (opt in).** `configure(default_redactors=True)` masks common secret shapes
   (API keys, bearer tokens, JWTs, private keys) in every string of the input, output, `raw` and
   error messages, on the JSON form, before anything leaves the process. Add your own redactors for
   PII. Pattern-based redaction is a baseline, not a guarantee. Metadata (for example a
   `client.base_url`) is not scrubbed; credentials embedded in a base URL are stripped.
2. **Credentials in HTTP headers are not stored.** The `httpx` instrumenter never records
   `authorization`, `cookie`, `x-api-key` and similar headers.
3. **The trace header goes only where you allow it.** `traceparent` is injected only to hosts in
   `inject_hosts`; the default is deny, so trace ids are not sent to your LLM provider or any
   third party.
4. **Payload limits.** `max_payload_bytes` caps any one string.

**What you must do**

1. **Turn redaction on** in production, and add redactors for the personal data in your prompts.
2. **Protect the API key** (`api_key` / `CHRONICLE_API_KEY`) like any credential; it is sent as a
   bearer token to the control plane.
3. **Turn `extract` off on internet-facing services.** A well-formed inbound `traceparent` proves
   neither that the trace exists nor that the sender is legitimate; a spoofed header attaches your
   spans to someone else's trace id. Trust and tenant scoping are future work (design 12.1).
4. **Treat hooks as trusted code.** Hooks see the arguments before redaction and the live result
   object and can change arguments. A security review of what hooks may see and do is future scope.
5. **Treat recorded inputs as untrusted.** A recorded prompt may contain a prompt-injection payload.
   Do not replay with `RUN` boundaries that act on the world without a sandbox.
6. **Rotate any secret that reaches the control plane.** If a credential is recorded, rotate it.

If you discover sensitive data that Chronicle sent where it should not have, report it through the
private channel above.
