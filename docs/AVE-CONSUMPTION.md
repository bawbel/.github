# How Bawbel consumes AVE

AVE is the open behavioral standard for agentic components. It is published at
[aveproject.org](https://aveproject.org) and governed separately, in
[aveproject/ave](https://github.com/aveproject/ave). Bawbel components that use AVE data
(today the scanner, gate, the MCP server, the PiranhaDB API, and the VS Code extension) are
consumers. A consumer reads the standard as published. It does not edit it, correct it, or
keep its own version of it.

Bawbel may add data of its own on top of AVE, in a Bawbel repository, for a Bawbel purpose,
such as capability tags for toxic flows. It never writes that data back into a record. Rule R7
says how it is kept.

## The rules

Every Bawbel component that uses AVE data follows these rules, and so does any repository
that starts to.

| # | Rule |
|---|---|
| R1 | **Read-only.** No Bawbel component writes to the AVE repository, opens a pull request or issue against it, or edits a record |
| R2 | **One source.** The published artifact `dist/ave-records-latest.json`, or a tagged release, fetched over HTTPS from `aveproject/ave`. Never per-record files at `main`, never the old `bawbel/ave` path, never another Bawbel service |
| R3 | **Pin and identify.** Whatever data a build or run used is recorded as `corpus_sha256` (of the exact bytes consumed), `schema_version`, `record_count`, `source_url` and `fetched_at` |
| R4 | **Check the schema.** Accept the majors it knows. Warn on a newer minor and ignore fields it does not understand. Refuse an unknown major |
| R5 | **No hand-copied AVE data.** Titles, severity, scores, crosswalks and detection hints are generated from the pinned artifact by a script, never typed. CI fails when the generated file is stale |
| R6 | **Display what AVE says.** Severity, AIVSS, crosswalk and mitigation shown to a user come from the corpus. A disagreement between a Bawbel table and AVE is a Bawbel bug |
| R7 | **Bawbel-derived data is labelled and owned by Bawbel.** For example the capability tags used for toxic flows. It lives in a Bawbel repo, is keyed by AVE id and the corpus hash it was derived for, and is never written back into a record. A record with no Bawbel mapping is "unmapped", never guessed |
| R8 | **Missing is missing.** An AVE id a component does not know prints "unverified". A field AVE does not provide is "not provided", and Bawbel does not fill it in |
| R9 | **Offline still works.** The scanner stays offline-capable through a vendored snapshot generated under R5 and stamped with its hash and date |
| R10 | **Disagreement goes upstream, through the maintainer.** If a consumer believes a record is wrong, the maintainer raises it in AVE's own process. No consumer fixes it locally |

`claims/register.yaml` entry C-21 checks that this table has R1 to R10, once each, in order.
It does not check that every component follows them. The section on Bawbel-owned data lists
where a component does not yet.

## The published artifact

AVE publishes its records as one JSON array in `aveproject/ave`:

| File | What it is |
|---|---|
| `dist/ave-records-latest.json` | All active records, regenerated when records change |
| `dist/ave-records-latest.manifest.json` | `schema_version`, `record_count`, `generated_at`, for a quick check before parsing |
| `dist/ave-records-v<version>.json` | A frozen snapshot, committed at each schema transition |

AVE's own implementer guide (`docs/specs/ave-implementer-guide.md` in `aveproject/ave`) says
to track the latest file or pin to a frozen snapshot, and not to auto-update at runtime.

### Fetch it at a commit, not at a branch

A URL that names a branch changes under you. A URL that names a commit returns the same bytes
every time:

```bash
COMMIT=<40-character commit of aveproject/ave>
URL=https://raw.githubusercontent.com/aveproject/ave/$COMMIT/dist/ave-records-latest.json
curl -fsSL "$URL" -o ave-records.json
```

### Verify what you consumed

AVE does not publish a digest of the file. R3 therefore asks the consumer to record its own:
the SHA-256 of the exact bytes it used.

```bash
sha256sum ave-records.json
git -C <clone of aveproject/ave> show $COMMIT:dist/ave-records-latest.json | sha256sum
```

The two digests are equal, because the commit URL serves the file as committed. Hash the
downloaded bytes, not a re-serialised copy: parsing and dumping the JSON changes the bytes
and so the digest.

Worked example, at `aveproject/ave` commit `6b9f1748c6ceedc1787af7a114361a216d3017d1`: the
file has 87 records, `schema_version` 1.1.0, and SHA-256
`e29c3c8bcdcffd74c9d9f0750b5d5b5c28da40321076e50def980507c72f6f70`. A later commit has its
own digest.

What R3 asks a build or run to record:

| Field | Value |
|---|---|
| `corpus_sha256` | Digest of the exact bytes consumed |
| `schema_version` | From the file or its manifest |
| `record_count` | Number of records parsed |
| `source_url` | The commit URL above |
| `fetched_at` | UTC time of the fetch |

## Bawbel-owned data keyed by AVE id

This is a snapshot, taken on 2026-10-23 from the `develop` branches (scanner `f263ecb`, gate
`5a0ceb7`, piranha-api `9321a6a`). It goes stale. Re-measure before relying on it.

| Component | Path | What it holds | Against the rules |
|---|---|---|---|
| scanner | `scanner/ave_meta.py` | Four AVE fields typed by hand, for 51 of the 87 published records | Breaks R5. Records without an entry fall under R8 |
| scanner | `scanner/owasp_mcp_map.py` | The scanner's own OWASP MCP mapping | Breaks R6. 26 of its 45 entries differ from the `owasp_mcp` field AVE publishes |
| scanner | `scanner/core/toxic_flows/capabilities.py` | A capability tag per AVE id, the vocabulary of toxic flow detection | Bawbel-owned, so R7 applies. It does not record the corpus hash it was derived for |
| gate | `mitigations/ave-mitigations.json`, `schemas/bawbel-ave-mitigations-v1.json` | Enforcement stanzas keyed by AVE id, kept out of the standard on purpose | Bawbel-owned, so R7 applies. It does not record the corpus hash it was derived for |
| gate | `schemas/ave-1.2.json` | A schema titled "AVE Record Schema v1.2", with its `$id` on `schemas.bawbel.io`. AVE publishes schema 1.0.0 and 1.1.0 | Not published by AVE, so R7 requires it to be labelled as Bawbel's |
| piranha-api | `sync_records.py`, `records/` | A copy of AVE records, read from the old `bawbel/ave` path at `main`, one file at a time | Breaks R2, R3 and R4 |

A new Bawbel-derived table is keyed by AVE id and by the corpus hash it was derived for. A
record it has no entry for is "unmapped", never guessed.

## When a consumer thinks AVE is wrong

Bawbel components do not fix records. They do not open issues or pull requests in
`aveproject/ave`, and they do not edit it. If a consumer believes a record is wrong, the AVE
maintainer raises it in AVE's own process (R10). No Bawbel tool or agent files an upstream
observation.

When Bawbel output differs from what AVE publishes, the defect is in Bawbel and is fixed on
the Bawbel side (R6).
