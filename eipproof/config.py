NAME = "eipproof"
SIMULATOR = "eels/consume-engine"
EIPS_REPO = "ethereum/EIPs"
EELS_REPO = "ethereum/execution-specs"
EIPS_BRANCH = "master"
INFRA_FAIL_RATIO = 0.05
CANDIDATE_WINDOW_DAYS = 14
TRACKED_STAGES = ["Scheduled", "Considered"]
STAGE_SHORT = {"Scheduled": "SFI", "Considered": "CFI", "Proposed": "PFI", "Declined": "DFI", "Included": "Included"}
MAX_ROWS = 40
CLIENTS = ["nethermind", "go-ethereum", "reth", "ethrex", "besu"]
CLIENT_LABEL = {"nethermind": "Nethermind", "go-ethereum": "Geth", "reth": "Reth", "ethrex": "ethrex", "besu": "Besu"}
CLIENT_REPO = {
    "nethermind": "NethermindEth/nethermind",
    "go-ethereum": "ethereum/go-ethereum",
    "reth": "paradigmxyz/reth",
    "ethrex": "lambdaclass/ethrex",
    "besu": "besu-eth/besu",
}
GITHUB = "https://github.com"
SELF_REPO = "NethermindEth/eipproof"
SITE_ROOT = "https://nethermindeth.github.io/eipproof"

FORKS = {
    "bogota": {
        "FORK": "bogota", "FORK_LABEL": "Bogotá", "FILL_FORK": "Bogota", "SUBDIR": "",
        "RELEASE_PREFIX": "tests-bogota-devnet@", "TEST_ROOT": "tests/bogota", "HIVE": "https://hive.ethpandaops.io/bogota",
        "META_EIP": "8081", "META_NAME": "Hegotá", "PROBE_EIP": "7906",
        "ROW_ORDER": ["8141", "7906", "8250", "8151", "8272", "8298", "4758", "8253"],
    },
    "glamsterdam": {
        "FORK": "glamsterdam", "FORK_LABEL": "Glamsterdam", "FILL_FORK": "Amsterdam", "SUBDIR": "glamsterdam",
        "RELEASE_PREFIX": "tests@", "TEST_ROOT": "tests/amsterdam", "HIVE": "https://hive.ethpandaops.io/glamsterdam",
        "META_EIP": "7773", "META_NAME": "Glamsterdam", "PROBE_EIP": "7928",
        "ROW_ORDER": [],
    },
}
DEFAULT_FORK = "bogota"


def use(fork):
    globals().update(FORKS[fork])
    globals()["SITE_URL"] = "/".join(p for p in (SITE_ROOT, FORKS[fork]["SUBDIR"]) if p)


use(DEFAULT_FORK)
