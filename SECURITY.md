# Security policy

## Intentional lab vulnerabilities

This repository contains an intentionally vulnerable PHP application and permissive test configuration. All variants, including those named `patched` and `mitigated`, retain the application's file-inclusion vulnerability. They are local research environments, not production deployment templates.

All Compose files publish HTTP on loopback. They also mount `lab/www/` read-write, so application changes can persist on the host. The mod_php variant relaxes container isolation. See the [README](README.md#shutdown-and-host-effects) before running a lab.

The project does not provide a confirmed reproduction of either CVE. See the [README](README.md#experimental-observer) for the observer's limits.

## Reporting

This is a personal learning project. Pull requests and code contributions are not accepted.

For an unexpected vulnerability in this project's tooling or a containment issue, use the repository host's private vulnerability reporting feature if enabled. If no private channel is available, open an issue requesting a private contact without including exploit details, credentials, or sensitive logs.

New PHP engine vulnerabilities should be reported through the [PHP security reporting process](https://github.com/php/php-src/security/policy), rather than disclosed as an ordinary issue in this lab repository. Reports about a third-party deployment belong with its owner or vendor.

No supported-release matrix or response-time commitment is currently defined for this research project. Runtime fixes and affected-version guidance come from PHP and distribution vendors.
