# Contributing

All settings live in `eipproof/config.py`. Data comes from public sources only: the EIPs repo, the EELS repo (execution-specs) and the hive listing for the fork.

## Set up and test

```
make site        # install, build site/ from the committed snapshot, serve it
make test        # unit, golden and site tests
make offline     # build site/ from the committed snapshot, no network
make check       # HTML balance and internal links of site/
make serve       # http://localhost:8765
```

`make build` fetches live data. It writes `snapshots/<date>.json` and `site/`. Commit a new snapshot only when a test needs the new data.

### Golden files

`tests/golden/` holds the JSON output and the sha256 of each HTML page, rendered from `snapshots/2026-11-03.json`. If you change the output on purpose:

1. Run `make golden`.
2. Read `git diff tests/golden`. Every changed file must follow from your change.
3. Commit the golden files in the same PR.

If `make test` fails on the golden test and you did not mean to change the output, fix the code instead.

## Add a client

1. Add the client name to `CLIENTS`. Use the hive name without the `_<tag>` suffix, for example `nethermind` for `nethermind_default`.
2. Add its label to `CLIENT_LABEL` and its GitHub repo to `CLIENT_REPO`.
3. Check that hive runs `eels/consume-engine` for it: `make build` prints one `run` line per client.
4. Run `make golden` if the committed snapshot changes the matrix, then `make test`.

A client without a hive run shows as "no run". It is not an error.

## Add an EIP

Rows come from the meta EIP (`META_EIP`): every EIP in `TRACKED_STAGES` (SFI, CFI) gets a row. An EIP gets client cells only when EELS has a test directory `tests/<fork>/eip<N>_*`. Without one, the row says "no tests yet".

1. To track an EIP the meta EIP does not list yet, add it to `ROW_ORDER`. This list also sets the row order.
2. Run `make build` and check the new row in `site/index.html`.
3. A spec change becomes "proven" only through a proof in `proofs/`. See "Prove a spec change" in the README.

## Add a fork

1. Add an entry to `FORKS` in `eipproof/config.py`: `FORK`, `FORK_LABEL`, `FILL_FORK`, `SUBDIR`, `RELEASE_PREFIX`, `TEST_ROOT`, `HIVE`, `META_EIP`, `META_NAME`, `PROBE_EIP` and `ROW_ORDER` (empty to follow the meta EIP).
2. Run `make build`. It writes `snapshots/<SUBDIR>/` and `site/<SUBDIR>/`, and the fork selector in the nav links the new fork.
3. Commit the new snapshot and add a test for the fork in `tests/test_site.py`.
4. Run `make golden` and `make test`.

## Add a data source

1. Fetch it in `eipproof/sources.py`. Use `http_get` or `git`, and cache large files under `cache/`.
2. Add a key to the snapshot in `build.snapshot()`. Keep the key deterministic: the same input data gives the same JSON.
3. Render it in `eipproof/render.py`, and add a JSON file under `api/` if other tools need it.
4. Add a test with a fixed input. Tests must not use the network.
5. If the site must show it after every deploy, add a check to `eipproof/smoke.py`.

## Snapshot history

The `pages` workflow stores each snapshot whose data changed on the `data` branch (`snapshots/<SUBDIR>/<taken_at>.json` and its `cases/`; Bogotá has an empty `SUBDIR`). Only the `archive` job can write, and only to that branch. Every page links to the permalink of its snapshot, `<SUBDIR>/s/<taken_at>/index.html`. `history.html` lists all snapshots. The newest `PERMALINKS` snapshots are rendered on the site. Older ones link to their JSON on the `data` branch.

## Code style

- Small diffs. Names that explain the code. No code comments: put the reason in the PR description.
- Pin every GitHub Action to a full commit SHA, with the version in a trailing `# vX.Y.Z`.

## Pull requests

1. Branch from `main` and open a PR. `main` is protected: the `test` check must pass on a branch that is up to date with `main`.
2. Describe what changed on the site and how you checked it (commands and output).
3. PRs merge by squash only (`gh pr merge --squash`). Merge commits and rebase merges are off.
4. After the merge, `pages` deploys. Its `smoke` job checks the live site.
