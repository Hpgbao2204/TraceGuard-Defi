// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IToken {
    function transferFrom(address, address, uint256) external returns (bool);
}

interface IPair {
    function token0() external view returns (address);
    function token1() external view returns (address);
    function getReserves() external view returns (uint112, uint112, uint32);
    function swap(uint256, uint256, address) external;
    function mint(address) external returns (uint256);
    function burn(address) external returns (uint256, uint256);
    function transferFrom(address, address, uint256) external returns (bool);
    function balanceOf(address) external view returns (uint256);
}

/// Shared V2 hop logic: input already sits in pools[0].
library V2Hops {
    function amountOut(uint256 amountIn, uint256 rIn, uint256 rOut) internal pure returns (uint256) {
        uint256 inFee = amountIn * 997;
        return (inFee * rOut) / (rIn * 1000 + inFee);
    }

    function run(address[] memory pools, address tokenIn, uint256 amountIn, address to)
        internal
        returns (uint256 out, address tokenOut)
    {
        out = amountIn;
        tokenOut = tokenIn;
        for (uint256 i = 0; i < pools.length; i++) {
            IPair p = IPair(pools[i]);
            address t0 = p.token0();
            (uint112 r0, uint112 r1,) = p.getReserves();
            bool zeroIn = tokenOut == t0;
            require(zeroIn || tokenOut == p.token1(), "path");
            uint256 o = zeroIn ? amountOut(out, r0, r1) : amountOut(out, r1, r0);
            address dest = i + 1 < pools.length ? pools[i + 1] : to;
            if (zeroIn) p.swap(0, o, dest);
            else p.swap(o, 0, dest);
            out = o;
            tokenOut = zeroIn ? p.token1() : t0;
        }
    }
}

/// V2-style router over an explicit pool path.
contract SimRouter {
    function swapExactIn(uint256 amountIn, uint256 amountOutMin, address[] calldata pools, address tokenIn, address to)
        external
        returns (uint256 out)
    {
        IToken(tokenIn).transferFrom(msg.sender, pools[0], amountIn);
        (out,) = V2Hops.run(pools, tokenIn, amountIn, to);
        require(out >= amountOutMin, "slippage");
    }

    /// Like UniswapV2Router02: desired amounts are cut to the pool's current ratio, so nothing is donated.
    function addLiquidity(address pool, uint256 amount0, uint256 amount1, address to) external returns (uint256) {
        IPair p = IPair(pool);
        (uint112 r0, uint112 r1,) = p.getReserves();
        if (r0 > 0 && r1 > 0) {
            uint256 opt1 = (amount0 * r1) / r0;
            if (opt1 <= amount1) amount1 = opt1;
            else amount0 = (amount1 * r0) / r1;
        }
        IToken(p.token0()).transferFrom(msg.sender, pool, amount0);
        IToken(p.token1()).transferFrom(msg.sender, pool, amount1);
        return p.mint(to);
    }

    function removeLiquidity(address pool, uint256 liquidity, address to) external returns (uint256, uint256) {
        IPair(pool).transferFrom(msg.sender, pool, liquidity);
        return IPair(pool).burn(to);
    }

    /// Withdraw the caller's whole LP position (used by JIT liquidity providers).
    function removeAll(address pool, address to) external returns (uint256, uint256) {
        IPair(pool).transferFrom(msg.sender, pool, IPair(pool).balanceOf(msg.sender));
        return IPair(pool).burn(to);
    }
}

/// Aggregator-style entry point: one call, several routes (split order), different calldata shape.
contract SimAggregator {
    struct Route {
        uint256 amountIn;
        address[] pools;
    }

    function multiSwap(Route[] calldata routes, address tokenIn, uint256 minOut, address to)
        external
        returns (uint256 total)
    {
        for (uint256 i = 0; i < routes.length; i++) {
            IToken(tokenIn).transferFrom(msg.sender, routes[i].pools[0], routes[i].amountIn);
            (uint256 o,) = V2Hops.run(routes[i].pools, tokenIn, routes[i].amountIn, to);
            total += o;
        }
        require(total >= minOut, "slippage");
    }
}
