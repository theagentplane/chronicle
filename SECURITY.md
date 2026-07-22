# Security Policy

## Supported versions

Chronicle is pre-1.0. Security fixes are applied to the latest released version
on the `main` branch.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue.

- Preferred: open a private [GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  for this repository.
- Or email the maintainers at **[INSERT SECURITY CONTACT EMAIL]**.

We aim to acknowledge reports within 3 business days and to provide a remediation
timeline after triage. Please give us a reasonable window to fix the issue before
public disclosure.

## Data-handling posture (read this before recording production traffic)

Chronicle captures the **execution DNA** of your agents. By design, an Envelope
can contain the most sensitive data in your system:

- the **full assembled prompt**,
- **graph / agent state**,
- **retrieved context chunks** (RAG results), and
- **tool inputs and outputs**.

Fixtures are **committed to your git repository** as regression tests. That means
un-redacted captures can leak **PII, secrets, credentials, and customer data**
into source control, where they are hard to fully remove.

**Rules of the road:**

1. **Never commit un-redacted production data.** Treat every captured Envelope as
   potentially containing secrets until proven otherwise.
2. **Redact before you extract.** Run scrubbers on Envelopes *before* they are
   written to a store, and definitely before `chronicle extract` moves them into
   `fixtures/`. (A pluggable redaction hook is on the roadmap — until then, scrub
   in your own capture wrapper.)
3. **Prefer synthetic or minimized fixtures.** Reduce each committed fixture to
   the smallest input that reproduces the incident.
4. **Treat captured inputs as untrusted.** Recorded prompts may contain
   prompt-injection payloads. Do not replay them in an environment where a live
   downstream boundary could act on them without sandboxing.
5. **Rotate any secret that lands in a fixture.** If a credential is captured and
   committed, rotate it — scrubbing git history is not a guarantee.

If you discover sensitive data already committed in fixtures, report it via the
private channel above so we can coordinate removal and rotation.
