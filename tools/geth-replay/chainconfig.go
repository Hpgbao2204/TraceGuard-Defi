package main

import (
	"fmt"
	"math/big"

	"github.com/ethereum/go-ethereum/params"
)

const (
	mainnetChainID   uint64 = 1
	avalancheChainID uint64 = 43114
	// anvilSimChainID is the local anvil chain of the RQ4 builder simulation
	// (eval/mev_sim), started with --hardfork shanghai.
	anvilSimChainID uint64 = 31337
)

type chainProfile struct {
	ID           uint64
	Name         string
	Experimental bool
}

func profileForChainID(chainID uint64) (chainProfile, error) {
	switch chainID {
	case mainnetChainID:
		return chainProfile{ID: chainID, Name: "ethereum-mainnet"}, nil
	case avalancheChainID:
		return chainProfile{ID: chainID, Name: "avalanche-c-chain", Experimental: true}, nil
	case anvilSimChainID:
		return chainProfile{ID: chainID, Name: "anvil-sim-shanghai", Experimental: true}, nil
	default:
		return chainProfile{}, fmt.Errorf("unsupported chain ID: %d", chainID)
	}
}

func getChainConfig(chainID uint64) (*params.ChainConfig, error) {
	profile, err := profileForChainID(chainID)
	if err != nil {
		return nil, err
	}
	if profile.ID == mainnetChainID {
		return params.MainnetChainConfig, nil
	}
	if profile.ID == anvilSimChainID {
		return anvilSimChainConfig(), nil
	}
	// The pinned go-ethereum version has no Avalanche profile. This provisional profile
	// changes only ChainID and inherits Mainnet fork rules; it is not paper-grade.
	config := *params.MainnetChainConfig
	config.ChainID = new(big.Int).SetUint64(avalancheChainID)
	return &config, nil
}

// anvilSimChainConfig matches `anvil --hardfork shanghai`: every block fork and
// the merge active from genesis, Shanghai from time 0, no Cancun or later (so no
// beacon-root or history-storage system calls in pre-execution). Simulation
// only; not a mainnet profile.
func anvilSimChainConfig() *params.ChainConfig {
	zero := big.NewInt(0)
	shanghai := uint64(0)
	return &params.ChainConfig{
		ChainID:                 new(big.Int).SetUint64(anvilSimChainID),
		HomesteadBlock:          zero,
		EIP150Block:             zero,
		EIP155Block:             zero,
		EIP158Block:             zero,
		ByzantiumBlock:          zero,
		ConstantinopleBlock:     zero,
		PetersburgBlock:         zero,
		IstanbulBlock:           zero,
		MuirGlacierBlock:        zero,
		BerlinBlock:             zero,
		LondonBlock:             zero,
		ArrowGlacierBlock:       zero,
		GrayGlacierBlock:        zero,
		MergeNetsplitBlock:      zero,
		TerminalTotalDifficulty: zero,
		ShanghaiTime:            &shanghai,
	}
}
