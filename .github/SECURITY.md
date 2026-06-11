# Security policy

## Reporting a vulnerability

Report suspected vulnerabilities privately via
[GitHub security advisories](https://github.com/jm-rivera/resolvekit/security/advisories/new)
or by email to <jorge.rivera@one.org>. Do not open a public issue for security
bugs.

You should receive an acknowledgement within a week. Only the latest released
version is supported with fixes.

## Scope notes

resolvekit resolves strings offline against bundled and downloaded data. Remote
data tiers are fetched over HTTPS from pinned GitHub Releases and verified
against SHA-256 checksums shipped in the package manifest; a mismatch aborts
the load. Reports about checksum bypass, path traversal in cache handling, or
unsafe deserialization are especially welcome.
