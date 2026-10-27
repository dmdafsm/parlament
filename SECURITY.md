# Security policy

This repository contains the code of a public website that republishes official data from the Romanian Parliament. It handles no user accounts, payments or personal data beyond what the chambers publish about MPs' public role.

## Reporting

Report vulnerabilities privately through the GitHub **Security** tab → **Report a vulnerability**. Do not open a public issue for a vulnerability.

## Scope

- The web application: injection (SQL, HTML), path handling (photos, CSV downloads), headers (CSP), denial of service through expensive queries.
- The collectors: handling of downloaded HTML (untrusted input), file paths under `data/`.
- The Docker setup and the CI workflow, hooks and dependency setup.

Out of scope: data that is wrong at the official source (report it to the chamber; we mirror it), and vulnerabilities in cdep.ro or senat.ro themselves.
