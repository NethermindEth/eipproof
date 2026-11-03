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
- **delta**: when the pin is behind, the spec change since the pin needs a covering test. An attestation in `attest/` names that test. Unsigned attestations ask for sign-off and never count as pass.
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

## Add a sign-off

Copy a file in `attest/`, set `status: signed` and your name in `author`, open a PR.
