# Security Policy

## Supported Scope

This is an educational lab repository for CCEN 356 Computer Networks. Security-sensitive examples include router automation, packet capture, generated TLS material, and lab network configuration.

## Reporting Issues

If you find a security issue in the code or documentation, report it privately to the repository owner or project team before opening a public issue.

## Public Release Notes

- Do not commit `.env` files, router passwords, private keys, generated certificates, packet captures, raw screenshots, or router backup files.
- Generated TLS files such as `server/key.pem` and `server/cert.pem` must stay local.
- Packet capture and router automation must only be used on networks and devices where you have explicit authorization.
- If this repository previously contained real router passwords, IOS password hashes, TLS keys, or private screenshots, rotate those credentials before publication.
- Use the `public-release` branch for publication if you need a clean single-commit branch without the original lab history.
