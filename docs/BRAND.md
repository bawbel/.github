# Third-party names and logos

Bawbel diagrams, pages and READMEs name other companies and projects. This page says how
they may appear. It exists because an earlier diagram carried a vendor's logo and described
vendors as underlying infrastructure, when no integration with any of them ships.

## Rules

1. Third parties appear as plain text names, never as logos, unless their written brand
   guidelines permit it. Read those guidelines before using a logo.
2. Say "compatible target" or "planned adapter". Never say "integration", "partner", or
   "powered by" without a shipped adapter and a published agreement.
3. A diagram that names a vendor is labelled with the state of the relationship:
   - `none`: named for context only
   - `target`: a planned adapter or compatibility, nothing built
   - `adapter shipped`: an adapter is in a Bawbel release
4. OpenShell, ACS and the MCP Registry may be named because Bawbel sits next to them. Say
   "adjacent", not "integrated".

## Before publishing a diagram

- [ ] No logo files from a vendor
- [ ] Every named vendor has a state label
- [ ] Typos checked. The last diagram had "Hug" and "Bawblbel"
- [ ] Every component's state matches `ecosystem-status.yaml`

## How it is checked

Claim C-18 in `claims/register.yaml` fails when an image file named after a vendor is in a
public Bawbel repository. It matches file names, not what is in the picture, so a logo saved
under another name passes. The checklist above is the control for that.
