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
CODE_CLIENTS = {
    "nethermind": {"label": "Nethermind", "layer": "el", "repo": "NethermindEth/nethermind", "branch": "master"},
    "go-ethereum": {"label": "Geth", "layer": "el", "repo": "ethereum/go-ethereum", "branch": "master"},
    "reth": {"label": "Reth", "layer": "el", "repo": "paradigmxyz/reth", "branch": "main"},
    "ethrex": {"label": "ethrex", "layer": "el", "repo": "lambdaclass/ethrex", "branch": "main"},
    "besu": {"label": "Besu", "layer": "el", "repo": "besu-eth/besu", "branch": "main"},
    "lighthouse": {"label": "Lighthouse", "layer": "cl", "repo": "sigp/lighthouse", "branch": "unstable"},
    "prysm": {"label": "Prysm", "layer": "cl", "repo": "OffchainLabs/prysm", "branch": "develop"},
    "lodestar": {"label": "Lodestar", "layer": "cl", "repo": "ChainSafe/lodestar", "branch": "unstable"},
    "nimbus": {"label": "Nimbus", "layer": "cl", "repo": "status-im/nimbus-eth2", "branch": "unstable"},
    "grandine": {"label": "Grandine", "layer": "cl", "repo": "grandinetech/grandine", "branch": "develop"},
}
EIP_LAYERS = {
    "7688": "cl", "7732": "cl", "8045": "cl", "8061": "cl", "8136": "cl", "8015": "cl", "8383": "cl",
    "7904": "el", "7975": "el", "8070": "el", "8159": "el", "8189": "el", "8077": "el", "8163": "el", "8173": "el", "8372": "el", "7907": "el",
    "8261": "both", "7805": "both", "8142": "both",
}
EIP_ALIASES = {"7732": ["ePBS"]}
GITHUB = "https://github.com"
SELF_REPO = "NethermindEth/eipproof"
SITE_ROOT = "https://nethermindeth.github.io/eipproof"
DATA_BRANCH = "data"
PERMALINKS = 48

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
