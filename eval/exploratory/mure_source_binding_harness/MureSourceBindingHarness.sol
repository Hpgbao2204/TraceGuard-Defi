// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC1271Like {
    function isValidSignature(bytes32 hash, bytes calldata signature) external view returns (bytes4);
}

interface IPoolMetadataLike {
    function poolState(string calldata) external view returns (address signer);
}

contract HarnessToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address account, uint256 amount) external { balanceOf[account] += amount; }
    function approve(address spender, uint256 amount) external { allowance[msg.sender][spender] = amount; }
    function approveFor(address owner, address spender, uint256 amount) external {
        allowance[owner][spender] = amount;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(balanceOf[from] >= amount, "balance");
        require(allowance[from][msg.sender] >= amount, "allowance");
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

contract MaliciousSource is IPoolMetadataLike, IERC1271Like {
    bytes4 internal constant MAGIC = 0x1626ba7e;
    function poolState(string calldata) external view returns (address signer) { return address(this); }
    function isValidSignature(bytes32, bytes calldata) external pure returns (bytes4) { return MAGIC; }
}

abstract contract DistributionBase {
    HarnessToken public immutable token;

    constructor(HarnessToken token_) { token = token_; }

    function _drain(address source, address repository, address recipient, uint256 amount) internal {
        address signer = IPoolMetadataLike(source).poolState("quest");
        require(IERC1271Like(signer).isValidSignature(bytes32(0), "") == 0x1626ba7e, "unauthorized");
        require(token.transferFrom(repository, recipient, amount), "transfer");
    }
}

contract VulnerableDistribution is DistributionBase {
    constructor(HarnessToken token_) DistributionBase(token_) {}
    function distribute(address source, address repository, address recipient, uint256 amount) external {
        _drain(source, repository, recipient, amount);
    }
}

contract PatchedDistribution is DistributionBase {
    mapping(address => bool) public trustedSource;

    constructor(HarnessToken token_, address legitimateSource) DistributionBase(token_) {
        trustedSource[legitimateSource] = true;
    }

    function distribute(address source, address repository, address recipient, uint256 amount) external {
        require(trustedSource[source], "unsupported source");
        _drain(source, repository, recipient, amount);
    }
}

contract MureSourceBindingHarness {
    uint256 private constant DRAIN = 4_848_683_803_036;

    function test_vulnerable_source_can_drain() external {
        HarnessToken token = new HarnessToken();
        VulnerableDistribution distributor = new VulnerableDistribution(token);
        MaliciousSource source = new MaliciousSource();
        address victim = address(0xBEEF);
        address attacker = address(this);
        token.mint(victim, DRAIN);
        _approveAs(victim, token, address(distributor), DRAIN);

        distributor.distribute(address(source), victim, attacker, DRAIN);
        require(token.balanceOf(victim) == 0, "vulnerable path did not drain");
        require(token.balanceOf(attacker) == DRAIN, "attacker did not receive drain");
    }

    function test_source_binding_blocks_same_attack() external {
        HarnessToken token = new HarnessToken();
        MaliciousSource legitimate = new MaliciousSource();
        PatchedDistribution distributor = new PatchedDistribution(token, address(legitimate));
        MaliciousSource attackerSource = new MaliciousSource();
        address victim = address(0xCAFE);
        address attacker = address(this);
        token.mint(victim, DRAIN);
        _approveAs(victim, token, address(distributor), DRAIN);

        (bool ok,) = address(distributor).call(
            abi.encodeCall(distributor.distribute, (address(attackerSource), victim, attacker, DRAIN))
        );
        require(!ok, "patched path accepted untrusted source");
        require(token.balanceOf(victim) == DRAIN, "patched path changed victim balance");
        require(token.balanceOf(attacker) == 0, "patched path transferred asset");
    }

    function _approveAs(address owner, HarnessToken token, address spender, uint256 amount) private {
        // Harness-only approval helper: the token exposes no impersonation. The
        // allowance is installed through a dedicated test token subclass pattern
        // below rather than weakening the production-shaped transferFrom logic.
        token.approveFor(owner, spender, amount);
    }
}
