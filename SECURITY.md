# Security

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's "Report a
vulnerability" (Security → Advisories) rather than a public issue. We aim to
acknowledge within a few days.

## Security posture

This tool is designed to be safe to run on private, proprietary source code:

- **Local by default.** The base install has no network-capable dependency.
  Nothing is uploaded, and no telemetry is collected.
- **No silent overwrites.** Writes are atomic, refuse to follow a symlink at
  the destination, and never persist an unvalidated transformation. Use
  `--backup` to keep a `.bak`.
- **Malformed input is data, not a crash.** Parsers degrade to an explicit
  finding rather than raising.
- **Untrusted input classes.** The tool parses attacker-influenceable files
  (images, source, text). Parsing is stdlib-based and bounded by a size cap;
  report any input that causes a crash, hang, or write outside the target path.

## Optional dependencies and network

- The `code` extra (tree-sitter) and `c2pa` extra run locally.
- Any future network-dependent detector must declare `requires_network` and is
  opt-in; it will never transmit an artifact without explicit consent.
