# eipproof

The status of an EIP in a client is a chain of evidence, not a label:

    EIP revision  ->  EELS test release  ->  client run in hive

Each cell of the matrix shows the weakest link of that chain and the reason.
No status comes from PR titles or from a grep for the EIP number.

Scope today: execution layer, fork `bogota`, simulator `eels/consume-engine`, 8 EIPs x 5 clients.

Live site: https://nethermindeth.github.io/eipproof/

## How a cell is decided

- **run**: the latest hive run of the client on the newest `tests-bogota-devnet@` release, filtered to the tests of the EIP.
- **pin**: the EIP commit that the EELS release was built from, compared with the EIP head on `ethereum/EIPs` master.
- **delta**: when the pin is behind, each spec change since the pin needs a covering test. A proof in `proofs/` holds a mutant: a patch to EELS that undoes the change. `eipproof prove` fills the EIP's tests with and without the mutant. The cases that flip from pass to fail are the covering tests, and they must pass in the client run. If no case flips, the change stays open.
- Open spec PRs are shown as an overlay only. They are not spec yet.
- A cell that is not proven becomes an item in the work queue (`queue.html`).

## Run it

Needs Python 3.11+ and git.

```bash
make test        # unit, golden and site tests
make golden      # rewrite tests/golden/ after an intended output change
make build       # fetch public data, write snapshots/ and site/
make offline     # rebuild site/ from the latest snapshot, no network
make check       # HTML balance and internal links of site/
make serve       # http://localhost:8765
python -m eipproof.cli why 7906 nethermind   # explain one cell
```

Data sources, all public: `ethereum/EIPs`, `ethereum/execution-specs` release tags, `https://hive.ethpandaops.io/bogota`.

## CI and deploy

- `ci` runs on every PR and on `main`: tests, an offline build, `make check` and the smoke check on the built site. `main` is protected: changes land through a PR with a green `test` check on an up-to-date branch.
- `pages` deploys only after `ci` passes on the same commit of `main`, and every hour after `make test`.
- If the live build fails, the site is built from the committed snapshot. Every page then shows "data from snapshot <date>", `api/status.json` has `"source": "snapshot"`, and the run has a warning. After 3 failures in a row the run opens or updates the issue "pages: live build falls back to snapshot"; the next live build closes it.
- After each deploy, `python -m eipproof.smoke <url> <sha>` checks the live pages and JSON, and fails the run if they are wrong.
- Run `pages` by hand with `force_fallback` to test the snapshot path.

## Check a client PR

```bash
python -m eipproof.cli pr-impact NethermindEth/nethermind 12612 --json impact.json
```

It prints Markdown: the tracked EIPs that the PR names (title, body, commits, paths, code) or whose SNAKE_CASE spec constants appear in its changed lines. For each EIP it also shows the spec version, whether the EELS tests are behind it, and the matrix cell. A match says the PR touches the EIP, not that it is correct. A PR that names neither the EIP nor one of its constants is not found.

In a client repo, `.github/actions/pr-impact` writes the same report to the job summary. It posts no comments and needs only `pull-requests: read`:

```yaml
- uses: NethermindEth/eipproof/.github/actions/pr-impact@<sha>
```

`prs.html` and `api/prs.json` list the open Nethermind PRs that touch a tracked EIP. Each hourly build refreshes them.

## Prove a spec change

1. Check out `ethereum/execution-specs` at the newest release tag.
2. Write a patch to `src/ethereum/forks/bogota/` that undoes the EIP change.
3. Run:

```bash
python -m eipproof.cli prove 8141 dc5d5fa6 --eels ../execution-specs \
  --tests tests/bogota/eip8141_frame_transactions --mutant m.patch -n 8
```

This writes `proofs/<eip>-<commit>.yaml` and copies the patch next to it. Open a PR with both files.
For a change with no behaviour, use `--editorial "<reason>"` instead.
