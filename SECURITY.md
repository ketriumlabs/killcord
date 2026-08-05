# Security Policy

## Reporting a Vulnerability

Please **do not** open a public issue for security vulnerabilities.

Report privately via [GitHub Security Advisories](../../security/advisories/new)
for this repository.

## Response SLO

- **Acknowledgement:** within 72 hours.
- **Fix or mitigation plan:** within 14 days for HIGH+ severity findings.

Findings that let a tripped action execute more than once (breaking the
at-most-once resume guarantee), let counters be reset or bypassed, or let a
denied action proceed anyway are always treated as HIGH severity — those are
the exact failure modes this library exists to prevent.

## Supported Versions

Only the latest `0.x` minor release is supported pre-1.0.

## Scope

In scope: the `killcord` package (core, snapshot, server, notify, adapters, CLI).
Third-party code that merely *uses* killcord is out of scope.
