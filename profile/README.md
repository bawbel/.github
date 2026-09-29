<div align="center">

# The Open Trust Layer for Autonomous Software Identity

**Authority. Behavior. Trust. Policy. Enforcement. Evidence.**

Autonomous software acts on instructions it reads at runtime. Bawbel declares what an
agent component is authorized to do, detects risky behavior before install, enforces
those declarations on MCP tool calls at runtime, and records what happened in a
hash-chained audit log that can be verified after the fact.

Bawbel is vendor-neutral. Runtime enforcement today covers MCP tool calls.

[Website](https://bawbel.io) ·
[Docs](https://bawbel.io/docs) ·
[Scanner](https://pypi.org/project/bawbel-scanner/) ·
[AVE Standard](https://aveproject.org) ·
[Contact](mailto:bawbel.io@gmail.com)

</div>

---

## Components

| Repo | What it does | Status | License |
|---|---|---|---|
| [scanner](https://github.com/bawbel/scanner) | Static detection for skill files, MCP servers, and system prompts. CLI, pre-commit, CI. JSON and SARIF. | v1.3.0 on PyPI | See repo |
| [gate](https://github.com/bawbel/gate) | Runtime enforcement for MCP agents. Capability manifests, session taint, trifecta invariant, hash-chained audit log. | v1.0 feature-complete, pre-release. Install from source | Apache 2.0 |
| [piranha-api](https://github.com/bawbel/piranha-api) | PiranhaDB. Threat intelligence and record lookup for agentic AI vulnerabilities, built on AVE. | Live | Apache 2.0 |
| [integrations](https://github.com/bawbel/integrations) | GitHub Actions, GitLab CI, Jenkins, CircleCI, Bitbucket Pipelines, pre-commit. | Live | Apache 2.0 |
| [bawbel-mcp](https://github.com/bawbel/bawbel-mcp) | MCP server exposing the scanner as agent-callable tools. Read-only, no private-data tools, no egress tools. | Live | Apache 2.0 |
| [VS Code extension](https://marketplace.visualstudio.com/items?itemName=bawbel.bawbel-scanner) | Inline diagnostics while editing agent code and MCP configs. | v1.1.0 on Marketplace | Apache 2.0 |

### AVE is a separate organization

Bawbel implements [AVE](https://aveproject.org), the open behavioral classification
standard for agentic AI components. AVE is governed independently at
[aveproject/ave](https://github.com/aveproject/ave) with its own maintainers, schema,
and contribution process. It is not a Bawbel product and any tool can emit AVE IDs.

```bash
curl -s https://api.aveproject.org      # neutral reference API, read-only
```

PiranhaDB is Bawbel's threat intelligence layer built on top of that standard. The
standard stays neutral; the intelligence product does not have to be.

Identity, reputation, and delegation are design work, not shipped code. See
[interoperability](#interoperability).

---

## Scanner: detect before install

```bash
pip install "bawbel-scanner[all]"

bawbel scan ./skills/ --recursive       # scan skill files
bawbel ssc https://server.example.com   # scan an MCP server card without starting it
bawbel report ./skill.md                # findings plus remediation guidance
```

The scanner never executes what it scans.

Six engines run in parallel: pattern, YARA, Semgrep, Magika content-type verification,
optional LLM semantic analysis, and an optional Docker behavioral sandbox. Findings are
deduplicated, then checked pairwise against built-in chain definitions so compound
attacks are reported as one higher-severity toxic flow rather than two isolated findings.

Every finding carries an AVE ID, an OWASP AIVSS v0.8 score, and OWASP MCP Top 10
mappings. A finding is a citation, not an opinion.

---

## Capability manifest: declare what a component may do

Default-deny declaration of what one component is permitted to do, under which argument
conditions, and how its output is classified.

```yaml
schema: bawbel/capability-manifest/v1
subject:
  kind: mcp-server
  name: github-mcp
provenance_class: tool.response.github
instruction_authority: none
trifecta:
  private_data: true
  untrusted_content: true
  external_comms: true
grants:
  tools:
    - name: get_issue
      effect: allow
    - name: create_pull_request
      effect: allow
      conditions:
        args.base_repo: {pattern: "myorg/*"}
    - name: "*"
      effect: deny
```

Absence of a grant is a deny. Effects move only down the lattice
(`allow` to `approve` to `deny`), never up, which makes the base grants a static upper
bound on what a session can do. Linting can therefore answer "can this deployment ever
exfiltrate" without executing anything.

```bash
bawbel-gate lint manifests/prod --forbid-effect allow --tools-with external_comms
```

---

## Gate: enforce at runtime, outside the model

Agent hosts grant flat trust to everything in context. A tool response, a skill file,
and a user message carry equal instruction authority inside the model, because the model
processes one token sequence with no privilege boundary. That is not fixable at the
model layer.

bawbel-gate is a deterministic proxy between the agent host and its MCP servers. Every
tool call passes three checks before reaching a real server:

```
CALL_RECEIVED (JSON-RPC)
  |
  +-- capability manifest    grant match by tool name; no match, deny
  +-- session taint          which provenance classes have entered this session
  +-- trifecta invariant     private AND untrusted AND egress, at least approve
  |
  +-- verdict   ALLOW   -> execute upstream
                APPROVE -> human gate, timeout denies
                DENY    -> JSON-RPC -32031, cites the AVE ID
  |
  +-- audit record  hash = sha256(canonical(record) || prev)
```

The trifecta invariant is the rule-of-two protection against prompt-injection
exfiltration. It is not configurable. No manifest field, environment variable, or debug
flag disables it.

The gate never reads model output. Every decision is made on structured JSON-RPC.

```bash
bawbel-gate serve --config gate.yaml --learn   # observe, enforce nothing
bawbel-gate learn synthesize --out manifests/  # draft manifests from what was observed
bawbel-gate verify tools.json manifests/github-mcp.cap.yaml --accept
bawbel-gate audit verify gate.audit.jsonl
```

---

## Interoperability

Runtime containment is becoming infrastructure. Bawbel does not compete with it.

Target architecture. No integration with the runtimes named below ships today, and
identity, reputation, and delegation are not built. The table after the diagram is the
current state.

```
             BAWBEL TRUST LAYER
                    │
       ┌────────────┼────────────┐
       │            │            │
   OpenShell     Cloudflare    AWS
       │            │            │
       ├────────────┼────────────┤
       │            │            │
    MCP          Agents       Tools
       │            │            │
       └────────────┼────────────┘
                    │
                 BAWBEL
                    │
       Identity / Authority
       Behavioral Trust
       AVE Intelligence
       Reputation
       Delegation
       Evidence
```

A sandbox answers whether a process may open a file or a socket. Bawbel is designed to
answer whether an entity should be trusted to take a class of action at all, given its
provenance, declared authority, observed behavior, and delegation chain, and to produce
the evidence for why. Today that covers provenance, declared authority, and observed
behavior for MCP tool calls.

What exists today:

| Layer | Component | State |
|---|---|---|
| Behavioral intelligence | AVE, separate org | Live, published standard |
| Threat intelligence | PiranhaDB | Live |
| Discovery | bawbel-scanner | Live |
| Policy | capability-manifest/v1 | Live |
| Enforcement | bawbel-gate | Pre-release |
| Evidence | gate hash-chained audit log | Pre-release |
| Identity, reputation, delegation | none | Design work, not started |

Interfaces are versioned so any component can be reimplemented independently, including
by a second implementer. Adapters for other runtimes are an open design question, not a
shipped feature.

---

## Contributing

Issues and pull requests are welcome on any repo. scanner and gate each have their own
CONTRIBUTING.md. Read the repo's DESIGN.md or ARCHITECTURE.md, where present, before
opening a PR that changes behavior.

Security issues: follow SECURITY.md in scanner or gate, or email
[bawbel.io@gmail.com](mailto:bawbel.io@gmail.com) for other repos. Do not open a public
issue for a vulnerability.

Contact: [bawbel.io@gmail.com](mailto:bawbel.io@gmail.com)
