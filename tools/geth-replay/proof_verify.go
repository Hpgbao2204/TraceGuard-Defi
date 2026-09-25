package main

import (
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"strings"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/rawdb"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/ethdb"
	"github.com/ethereum/go-ethereum/rlp"
	"github.com/ethereum/go-ethereum/trie"
)

type proofFile struct {
	SchemaVersion int `json:"schema_version"`
	Header        struct {
		Number    string `json:"number"`
		Hash      string `json:"hash"`
		StateRoot string `json:"stateRoot"`
	} `json:"header"`
	Proofs []proofItem `json:"proofs"`
}

type proofItem struct {
	Address string `json:"address"`
	Code    string `json:"code"`
	Proof   struct {
		Balance      string   `json:"balance"`
		Nonce        string   `json:"nonce"`
		CodeHash     string   `json:"codeHash"`
		AccountProof []string `json:"accountProof"`
		StorageProof []struct {
			Key   string   `json:"key"`
			Value string   `json:"value"`
			Proof []string `json:"proof"`
		} `json:"storageProof"`
		StorageHash string `json:"storageHash"`
	} `json:"proof"`
}

func addNodes(db ethdb.KeyValueWriter, nodes []string) error {
	for _, encoded := range nodes {
		node := common.Hex2Bytes(strings.TrimPrefix(encoded, "0x"))
		if len(node) == 0 {
			return fmt.Errorf("empty proof node")
		}
		if err := db.Put(crypto.Keccak256(node), node); err != nil {
			return err
		}
	}
	return nil
}

// verifyProofFileAgainstAccounts verifies that every value which will be
// injected into the relevant-substate StateDB is the value authenticated by
// its EIP-1186 proof.  Trie-path verification alone is insufficient because a
// caller could otherwise inject values unrelated to the verified paths.
func verifyProofFileAgainstAccounts(path string, accounts map[string]account) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var file proofFile
	if err := json.Unmarshal(data, &file); err != nil {
		return err
	}
	root := common.HexToHash(file.Header.StateRoot)
	proofAccounts := make(map[string]proofItem, len(file.Proofs))
	for _, item := range file.Proofs {
		proofAccounts[strings.ToLower(common.HexToAddress(item.Address).Hex())] = item
	}
	for address, injected := range accounts {
		canonical := strings.ToLower(common.HexToAddress(address).Hex())
		item, ok := proofAccounts[canonical]
		if !ok {
			return fmt.Errorf("injected account %s has no authenticated proof", canonical)
		}
		proofSlots := make(map[string]struct{}, len(item.Proof.StorageProof))
		for _, slot := range item.Proof.StorageProof {
			proofSlots[strings.ToLower(common.HexToHash(slot.Key).Hex())] = struct{}{}
		}
		for slot := range injected.Storage {
			canonicalSlot := strings.ToLower(common.HexToHash(slot).Hex())
			if _, ok := proofSlots[canonicalSlot]; !ok {
				return fmt.Errorf("injected account %s storage %s has no authenticated proof", canonical, canonicalSlot)
			}
		}
	}
	for _, item := range file.Proofs {
		address := strings.ToLower(common.HexToAddress(item.Address).Hex())
		a, ok := accounts[address]
		if !ok {
			continue
		}
		db := rawdb.NewMemoryDatabase()
		if err := addNodes(db, item.Proof.AccountProof); err != nil {
			return err
		}
		value, err := trie.VerifyProof(root, crypto.Keccak256(common.HexToAddress(item.Address).Bytes()), db)
		if err != nil {
			return fmt.Errorf("account %s: %w", address, err)
		}
		if value == nil {
			if a.Balance != "" && quantity(a.Balance).Sign() != 0 || a.Nonce != 0 || a.Code != "0x" && a.Code != "" || len(a.Storage) != 0 {
				return fmt.Errorf("account %s: proof says absent but injected state is non-empty", address)
			}
			continue
		}
		var fields []rlp.RawValue
		if err := rlp.DecodeBytes(value, &fields); err != nil || len(fields) != 4 {
			return fmt.Errorf("account %s invalid rlp", address)
		}
		var nonce uint64
		if err := rlp.DecodeBytes(fields[0], &nonce); err != nil || nonce != a.Nonce {
			return fmt.Errorf("account %s nonce does not match proof", address)
		}
		var balance big.Int
		if err := rlp.DecodeBytes(fields[1], &balance); err != nil || balance.Cmp(quantity(a.Balance)) != 0 {
			return fmt.Errorf("account %s balance does not match proof", address)
		}
		var storageRoot, codeHash common.Hash
		if err := rlp.DecodeBytes(fields[2], &storageRoot); err != nil || storageRoot != common.HexToHash(item.Proof.StorageHash) {
			return fmt.Errorf("account %s storage root does not match proof", address)
		}
		if err := rlp.DecodeBytes(fields[3], &codeHash); err != nil {
			return fmt.Errorf("account %s code hash decode failed", address)
		}
		var code []byte
		if a.Code != "" && a.Code != "0x" {
			code, err = hexutil.Decode(a.Code)
			if err != nil {
				return fmt.Errorf("account %s invalid injected code: %w", address, err)
			}
		}
		if crypto.Keccak256Hash(code) != codeHash || item.Proof.CodeHash != "" && common.HexToHash(item.Proof.CodeHash) != codeHash {
			return fmt.Errorf("account %s code hash does not match proof", address)
		}
		normalizedStorage := make(map[string]string, len(a.Storage))
		for key, value := range a.Storage {
			normalizedStorage[strings.ToLower(common.HexToHash(key).Hex())] = value
		}
		for _, slot := range item.Proof.StorageProof {
			canonicalSlot := strings.ToLower(common.HexToHash(slot.Key).Hex())
			injectedValue, ok := normalizedStorage[canonicalSlot]
			if !ok {
				continue
			}
			var proofValue []byte
			if storageRoot != types.EmptyRootHash {
				sdb := rawdb.NewMemoryDatabase()
				if err := addNodes(sdb, slot.Proof); err != nil {
					return err
				}
				rawValue, err := trie.VerifyProof(storageRoot, crypto.Keccak256(common.HexToHash(slot.Key).Bytes()), sdb)
				if err != nil {
					return fmt.Errorf("account %s storage %s: %w", address, slot.Key, err)
				}
				if rawValue != nil && rlp.DecodeBytes(rawValue, &proofValue) != nil {
					return fmt.Errorf("account %s storage %s value decode failed", address, slot.Key)
				}
			}
			if common.BytesToHash(proofValue) != common.HexToHash(slot.Value) || common.BytesToHash(proofValue) != common.HexToHash(injectedValue) {
				return fmt.Errorf("account %s storage %s value does not match proof", address, slot.Key)
			}
		}
	}
	return nil
}

func loadAuthenticatedInitialState(path string, discovered map[string]map[string]struct{}, target *types.Header, parent *types.Header) (AuthenticatedInitialState, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return AuthenticatedInitialState{}, err
	}
	var file proofFile
	if err := json.Unmarshal(data, &file); err != nil {
		return AuthenticatedInitialState{}, err
	}
	if file.SchemaVersion < 3 {
		return AuthenticatedInitialState{}, fmt.Errorf("proof artifact schema %d lacks authenticated code bytes", file.SchemaVersion)
	}
	if file.Header.StateRoot == "" {
		return AuthenticatedInitialState{}, fmt.Errorf("authenticated state proof has no state root")
	}
	if file.Header.Number != fmt.Sprintf("0x%x", target.Number.Uint64()-1) ||
		common.HexToHash(file.Header.Hash) != parent.Hash() ||
		common.HexToHash(file.Header.StateRoot) != parent.Root {
		return AuthenticatedInitialState{}, fmt.Errorf("proof header is not the canonical target parent")
	}
	authenticated, err := authenticatedAccounts(file, discovered)
	if err != nil {
		return AuthenticatedInitialState{}, err
	}
	return AuthenticatedInitialState{
		Accounts:  authenticated,
		StateRoot: common.HexToHash(file.Header.StateRoot),
		Block:     target.Number.Uint64() - 1,
	}, nil
}

// authenticatedAccounts constructs the StateDB input from decoded proof
// values. The trace-derived map is used only to identify requested addresses
// and storage keys; it is never forwarded as initial state.
func authenticatedAccounts(file proofFile, discovered map[string]map[string]struct{}) (map[string]account, error) {
	root := common.HexToHash(file.Header.StateRoot)
	items := make(map[string]proofItem, len(file.Proofs))
	for _, item := range file.Proofs {
		items[strings.ToLower(common.HexToAddress(item.Address).Hex())] = item
	}
	out := make(map[string]account, len(discovered))
	for rawAddress, requested := range discovered {
		address := strings.ToLower(common.HexToAddress(rawAddress).Hex())
		item, ok := items[address]
		if !ok {
			return nil, fmt.Errorf("missing authenticated account %s", address)
		}
		db := rawdb.NewMemoryDatabase()
		if err := addNodes(db, item.Proof.AccountProof); err != nil {
			return nil, err
		}
		value, err := trie.VerifyProof(root, crypto.Keccak256(common.HexToAddress(address).Bytes()), db)
		if err != nil {
			return nil, fmt.Errorf("account %s: %w", address, err)
		}
		if value == nil {
			out[address] = account{Exists: boolPtr(false)}
			continue
		}
		var fields []rlp.RawValue
		if err := rlp.DecodeBytes(value, &fields); err != nil || len(fields) != 4 {
			return nil, fmt.Errorf("account %s invalid rlp", address)
		}
		var nonce uint64
		var balance big.Int
		var storageRoot, codeHash common.Hash
		if err := rlp.DecodeBytes(fields[0], &nonce); err != nil || rlp.DecodeBytes(fields[1], &balance) != nil || rlp.DecodeBytes(fields[2], &storageRoot) != nil || rlp.DecodeBytes(fields[3], &codeHash) != nil {
			return nil, fmt.Errorf("account %s invalid authenticated fields", address)
		}
		code := item.Code
		if code == "" {
			return nil, fmt.Errorf("account %s missing authenticated code", address)
		}
		codeBytes, err := hexutil.Decode(code)
		if err != nil {
			return nil, fmt.Errorf("account %s invalid code: %w", address, err)
		}
		if crypto.Keccak256Hash(codeBytes) != codeHash {
			return nil, fmt.Errorf("account %s code hash mismatch", address)
		}
		storage := make(map[string]string, len(requested))
		proofSlots := make(map[string]struct{}, len(item.Proof.StorageProof))
		for _, slot := range item.Proof.StorageProof {
			canonical := strings.ToLower(common.HexToHash(slot.Key).Hex())
			proofSlots[canonical] = struct{}{}
			if _, needed := requested[canonical]; !needed {
				continue
			}
			var decoded []byte
			if storageRoot != types.EmptyRootHash {
				sdb := rawdb.NewMemoryDatabase()
				if err := addNodes(sdb, slot.Proof); err != nil {
					return nil, err
				}
				raw, err := trie.VerifyProof(storageRoot, crypto.Keccak256(common.HexToHash(slot.Key).Bytes()), sdb)
				if err != nil {
					return nil, err
				}
				if raw != nil {
					if err := rlp.DecodeBytes(raw, &decoded); err != nil {
						return nil, err
					}
				}
			}
			storage[canonical] = common.BytesToHash(decoded).Hex()
		}
		for slot := range requested {
			if _, ok := proofSlots[slot]; !ok {
				return nil, fmt.Errorf("account %s storage %s has no authenticated proof", address, slot)
			}
		}
		out[address] = account{Balance: "0x" + balance.Text(16), Nonce: nonce, Code: hexutil.Encode(codeBytes), Storage: storage, StorageRoot: storageRoot.Hex(), Exists: boolPtr(true)}
	}
	return out, nil
}

func boolPtr(value bool) *bool { return &value }

func verifyProofFile(path string) (int, int, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, 0, err
	}
	var file proofFile
	if err := json.Unmarshal(data, &file); err != nil {
		return 0, 0, err
	}
	root := common.HexToHash(file.Header.StateRoot)
	accountsOK, storageOK := 0, 0
	for _, item := range file.Proofs {
		db := rawdb.NewMemoryDatabase()
		if err := addNodes(db, item.Proof.AccountProof); err != nil {
			return accountsOK, storageOK, err
		}
		value, err := trie.VerifyProof(root, crypto.Keccak256(common.HexToAddress(item.Address).Bytes()), db)
		if err != nil {
			return accountsOK, storageOK, fmt.Errorf("account %s: %w", item.Address, err)
		}
		accountsOK++
		if len(item.Proof.StorageProof) == 0 {
			continue
		}
		if value == nil {
			// eth_getProof may return requested storage keys even when the
			// account itself is absent.  The absent account has the canonical
			// empty storage trie, so every requested slot is zero.
			storageOK += len(item.Proof.StorageProof)
			continue
		}
		var fields []rlp.RawValue
		if err := rlp.DecodeBytes(value, &fields); err != nil || len(fields) != 4 {
			return accountsOK, storageOK, fmt.Errorf("account %s invalid rlp", item.Address)
		}
		var storageRoot common.Hash
		if err := rlp.DecodeBytes(fields[2], &storageRoot); err != nil {
			return accountsOK, storageOK, fmt.Errorf("account %s invalid storage root", item.Address)
		}
		for _, slot := range item.Proof.StorageProof {
			if storageRoot == types.EmptyRootHash {
				// The canonical empty storage trie has no proof nodes. A proof
				// for any slot is therefore the canonical zero value.
				storageOK++
				continue
			}
			sdb := rawdb.NewMemoryDatabase()
			if err := addNodes(sdb, slot.Proof); err != nil {
				return accountsOK, storageOK, err
			}
			if _, err := trie.VerifyProof(storageRoot, crypto.Keccak256(common.HexToHash(slot.Key).Bytes()), sdb); err != nil {
				return accountsOK, storageOK, fmt.Errorf("storage %s/%s: %w", item.Address, slot.Key, err)
			}
			storageOK++
		}
	}
	return accountsOK, storageOK, nil
}

// proofAccountExistence returns the authenticated account-presence bit for
// selected addresses.  A valid proof with a nil trie value means the account
// is absent, which is different from an existing empty account for EIP-7702
// gas accounting.
func proofAccountExistence(path string, addresses []string) (map[string]bool, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var file proofFile
	if err := json.Unmarshal(data, &file); err != nil {
		return nil, err
	}
	wanted := make(map[string]struct{}, len(addresses))
	for _, address := range addresses {
		wanted[strings.ToLower(common.HexToAddress(address).Hex())] = struct{}{}
	}
	result := make(map[string]bool, len(wanted))
	root := common.HexToHash(file.Header.StateRoot)
	for _, item := range file.Proofs {
		address := strings.ToLower(common.HexToAddress(item.Address).Hex())
		if _, ok := wanted[address]; !ok {
			continue
		}
		db := rawdb.NewMemoryDatabase()
		if err := addNodes(db, item.Proof.AccountProof); err != nil {
			return nil, err
		}
		value, err := trie.VerifyProof(root, crypto.Keccak256(common.HexToAddress(item.Address).Bytes()), db)
		if err != nil {
			return nil, fmt.Errorf("account %s: %w", item.Address, err)
		}
		result[address] = value != nil
	}
	for address := range wanted {
		if _, ok := result[address]; !ok {
			return nil, fmt.Errorf("proof missing required authorization account %s", address)
		}
	}
	return result, nil
}
