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
make test        # unit + snapshot tests
make build       # fetch public data, write snapshots/ and site/
make offline     # rebuild site/ from the latest snapshot, no network
make serve       # http://localhost:8765
python -m eipproof.cli why 7906 nethermind   # explain one cell
```

Data sources, all public: `ethereum/EIPs`, `ethereum/execution-specs` release tags, `https://hive.ethpandaops.io/bogota`.

The site is rebuilt every hour by `.github/workflows/pages.yml`.

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
