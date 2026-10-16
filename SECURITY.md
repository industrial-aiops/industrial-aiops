# Security policy

iaiops reads from — and, behind dry-run, named approval and undo, can write to —
industrial control systems. A vulnerability here can reach a plant floor, so
reports are welcome and handled as below.

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

- **Preferred:** GitHub private vulnerability reporting —
  [Report a vulnerability](https://github.com/industrial-aiops/industrial-aiops/security/advisories/new)
  (repository → Security → Advisories). Only the maintainers see it.
- **Alternative:** e-mail **zhouwei008@gmail.com** with `[iaiops security]` in
  the subject. If you need encryption, say so in a first, content-free message
  and a key will be arranged.

Please include the affected version (`iaiops --version`), the component (CLI,
MCP server, a connector, a container image or the Margo package), the
configuration needed to reproduce, and the impact you observed. Proof-of-concept
code is welcome; **never test against equipment you do not own or operate.**

Vulnerabilities in third-party components shipped with iaiops (Python
dependencies, base images) are in scope too — report them here as well as
upstream, so we can ship the fixed version. Vulnerabilities in the industrial
devices iaiops talks to (a PLC, a broker, an OPC UA server) belong to that
device's vendor; we will help route them if asked.

## What happens next

| Step | Target |
|---|---|
| Acknowledge the report | within 7 days |
| First assessment (reproduced or not, severity by CVSS v4) | within 30 days |
| Fix released for critical / high severity | within 90 days of the report, sooner when exploited |
| Fix released for medium / low severity | in a following regular release |

These are targets of a small maintainer team, not contractual service levels.
You will be told if one slips, and why.

## Coordinated disclosure

- We ask reporters to keep a vulnerability private until a fix is released, or
  for **90 days** from the report, whichever comes first. We will not ask for
  longer except to finish a fix already in progress, and will say so.
- When the fix is released we publish a **GitHub Security Advisory** for it,
  request a CVE identifier through GitHub where the issue qualifies, and credit
  the reporter unless they prefer otherwise.
- The advisory states: a description of the vulnerability, the affected and
  fixed versions, the impact, a severity, and what users must do (upgrade,
  configuration change, or mitigation until they can upgrade). The release's
  CHANGELOG entry carries a `### Security` section linking the advisory.
- Exceptionally, publication of a fixed vulnerability's details may be delayed
  until users have had the possibility to apply the patch, where publishing
  sooner would put them at greater risk (as Regulation (EU) 2024/2847, Annex I
  Part II(4), allows). The advisory then says that it was delayed.

## Supported versions

Security fixes are made on the **latest released minor version** and shipped as
a new patch release on PyPI, as signed container images, and as a signed Margo
application package. Security updates are free of charge. Older versions are
not patched; upgrade to the latest release.

## What the project does on its own side

- Every change runs a static security scan (bandit, zero Medium+ findings) and
  a **dependency-vulnerability scan** of the locked dependency set (pip-audit
  against the PyPI advisory database); a known vulnerability fails the build
  unless it is listed, with a reason, in `.github/pip-audit-ignore.txt`.
- Each release publishes a **CycloneDX SBOM** of the locked, tested dependency
  set as a release asset.
- PyPI uploads go through Trusted Publishing (no long-lived token) with
  attestations; container images and the Margo package are cosign-signed
  (public key `deploy/margo/cosign.pub`).
- Dependabot alerts and security updates, secret scanning and push protection
  are enabled on the repository.

## Regulatory note

This policy is the coordinated vulnerability disclosure policy referred to in
Regulation (EU) 2024/2847 (Cyber Resilience Act), Annex I Part II(5), and the
contact address referred to in Part II(6). Whether and how the CRA applies to the
free MIT edition is not yet assessed (see `iaiops compliance --framework cra`);
the policy is applied regardless. Where the CRA's Article 14 reporting
obligations apply to a release, actively exploited vulnerabilities and severe
incidents will be notified as that article requires.
