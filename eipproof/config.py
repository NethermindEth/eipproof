NAME = "eipproof"
FORK = "bogota"
RELEASE_PREFIX = "tests-bogota-devnet@"
TEST_ROOT = "tests/bogota"
HIVE = "https://hive.ethpandaops.io/bogota"
SIMULATOR = "eels/consume-engine"
EIPS_REPO = "ethereum/EIPs"
EELS_REPO = "ethereum/execution-specs"
EIPS_BRANCH = "master"
INFRA_FAIL_RATIO = 0.05
CANDIDATE_WINDOW_DAYS = 14
ROW_ORDER = ["8141", "7906", "8250", "8151", "8272", "8298", "4758", "8253"]
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
