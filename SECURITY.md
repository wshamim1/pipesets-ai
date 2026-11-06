# Security Policy

## Reporting a vulnerability

Please **don't** open a public issue for security problems.

Report privately through GitHub: go to the repository's **Security** tab and choose
**Report a vulnerability**. Include:

- what is affected (component, endpoint, version or commit)
- steps to reproduce, or a proof of concept
- the impact you expect (data exposure, code execution, auth bypass, …)

You should get a reply within 7 days. Once a fix is ready, we'll agree a disclosure date with you
and credit you in the release notes unless you'd rather not be named.

## Supported versions

Only the latest release on `main` receives security fixes.

## Scope

In scope: the backend API (`/api/*`, `/v1/*`, MCP), authentication and access control, secret
storage, the custom-tool sandbox, guardrails, public chat links, and the deployment manifests in
`deploy/`.

Out of scope: vulnerabilities in third-party LLM providers or dependencies (report those
upstream), and setups that ignore the warnings in the README's
[Known limitations](README.md#known-limitations), such as running custom tools without the
sandbox.
