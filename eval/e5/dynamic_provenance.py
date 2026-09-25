"""Strict, synthetic-testable EVM value/dependency provenance engine."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass(frozen=True)
class ValueProvenance:
    value_id: str; value: str|None; producer_opcode: str; frame_id: str|None
    storage_context: str|None; pc: int|None; depth: int|None; parents: tuple[str,...]=()

@dataclass
class Observation:
    observation_id: str; kind: str; pc: int|None; depth: int|None; frame_id: str|None
    values: list[str]=field(default_factory=list); parents: list[str]=field(default_factory=list)
    trace_index: int|None = None
    branch_target: int|None = None
    branch_taken: bool|None = None

class ProvenanceError(ValueError): pass

@dataclass
class _FrameState:
    stack: list[str]=field(default_factory=list)
    memory: dict[int,str]=field(default_factory=dict)
    returndata: dict[int,str]=field(default_factory=dict)
    initialized: bool=False

class DynamicProvenance:
    """Track value parents without guessing frame or storage ownership."""
    BINARY={"ADD","SUB","MUL","DIV","MOD","AND","OR","XOR","LT","GT","EQ","SLT","SGT","SHL","SHR","SAR","ADDMOD","MULMOD"}
    UNARY={"ISZERO","NOT","CALLER","ORIGIN","ADDRESS","CALLVALUE","CALLDATASIZE","CODESIZE","RETURNDATASIZE","MSIZE","PC","GAS","TIMESTAMP","NUMBER","COINBASE","DIFFICULTY","PREVRANDAO","BASEFEE","CHAINID","SELFBALANCE","BLOBBASEFEE","BLOBHASH"}
    ENV_POP_PUSH={"BALANCE","EXTCODESIZE","EXTCODEHASH"}
    COPY3={"CALLDATACOPY","CODECOPY","RETURNDATACOPY","MCOPY"}
    CALL_ARITY={"CALL":7,"CALLCODE":7,"DELEGATECALL":6,"STATICCALL":6}
    def __init__(self, *, strict: bool=True, verify_shadow_stack: bool=True, allow_frame_bootstrap: bool=False):
        self.strict=strict; self.verify_shadow_stack=verify_shadow_stack
        self.allow_frame_bootstrap=allow_frame_bootstrap
        self.values={}; self.observations=[]; self._counter=0; self._frames={}
        self.last_write={}; self.shadow_checks=0; self.shadow_mismatches=[]; self.shadow_unverified=0; self.shadow_resolved=0; self.shadow_bootstrapped_frames=0; self._pending_branches={}
        self._frame_return_roots={}
        self.frame_code={}; self.frame_meta={}; self.frame_parent={}; self._active_frames={}
    def _frame(self, log):
        frame=log.get("frameId")
        if not isinstance(frame,str): raise ProvenanceError(f"missing frameId at pc={log.get('pc')}")
        return self._frames.setdefault(frame,_FrameState())
    def _new(self, op, log, parents=(), value=None):
        vid=f"v{self._counter}"; self._counter+=1
        self.values[vid]=ValueProvenance(vid,value,op,log.get("frameId"),log.get("storageContextAddress"),log.get("pc"),log.get("depth"),tuple(parents)); return vid
    def _computed(self, op, parents, concrete=None):
        vals = list(concrete) if concrete is not None else [self._int(self.values[p].value) for p in parents]
        if any(v is None for v in vals):
            return None
        mask = (1 << 256) - 1
        def signed(v):
            v &= mask
            return v - (1 << 256) if v >= (1 << 255) else v
        try:
            if op == "ADD": result = vals[0] + vals[1]
            elif op == "SUB": result = vals[0] - vals[1]
            elif op == "MUL": result = vals[0] * vals[1]
            elif op in {"DIV", "SDIV"}: result = 0 if vals[1] == 0 else vals[0] // vals[1]
            elif op in {"MOD", "SMOD"}: result = 0 if vals[1] == 0 else vals[0] % vals[1]
            elif op == "AND": result = vals[0] & vals[1]
            elif op == "OR": result = vals[0] | vals[1]
            elif op == "XOR": result = vals[0] ^ vals[1]
            elif op == "LT": result = int(vals[0] < vals[1])
            elif op == "SLT": result = int(signed(vals[0]) < signed(vals[1]))
            elif op == "GT": result = int(vals[0] > vals[1])
            elif op == "SGT": result = int(signed(vals[0]) > signed(vals[1]))
            elif op == "EQ": result = int(vals[0] == vals[1])
            elif op == "SHL": result = vals[1] << vals[0]
            elif op == "SHR": result = vals[1] >> vals[0]
            elif op == "SAR": result = signed(vals[1]) >> vals[0]
            elif op == "ADDMOD": result = 0 if vals[2] == 0 else (vals[0] + vals[1]) % vals[2]
            elif op == "MULMOD": result = 0 if vals[2] == 0 else (vals[0] * vals[1]) % vals[2]
            else: return None
            return str(result & mask)
        except (IndexError, ZeroDivisionError):
            return None
    @staticmethod
    def _int(value):
        if not isinstance(value, str):
            return None
        try:
            return int(value, 0)
        except ValueError:
            try:
                return int(value)
            except ValueError:
                return None
    @staticmethod
    def _pop(stack,count,log):
        if len(stack)<count: raise ProvenanceError(f"stack underflow at pc={log.get('pc')} op={log.get('op')}")
        return [stack.pop() for _ in range(count)]
    def _observe(self,kind,log,values):
        parents=sorted({p for v in values for p in self.values[v].parents})
        observation=Observation(f"o{len(self.observations)}",kind,log.get("pc"),log.get("depth"),log.get("frameId"),list(values),parents,log.get("callTraceIndex"))
        self.observations.append(observation)
        return observation
    def _resolve_pending_branch(self, log):
        frame_id=log.get("frameId")
        pending=self._pending_branches.pop(frame_id, None)
        if pending is not None:
            target=pending.branch_target
            pending.branch_taken=(target is not None and log.get("pc") == target)
    def _verify_shadow(self, log, frame):
        if not self.verify_shadow_stack:
            return
        observed = log.get("stack")
        if not isinstance(observed, list):
            raise ProvenanceError(f"missing concrete stack snapshot at pc={log.get('pc')}")
        self.shadow_checks += 1
        if len(observed) != len(frame.stack):
            msg=f"shadow stack height mismatch at pc={log.get('pc')}: model={len(frame.stack)} observed={len(observed)}"
            self.shadow_mismatches.append(msg)
            raise ProvenanceError(msg)
        for value_id, concrete in zip(frame.stack, observed):
            known = self._int(self.values[value_id].value)
            actual = self._int(concrete)
            if known is None:
                if actual is None:
                    self.shadow_unverified += 1
                else:
                    old=self.values[value_id]
                    self.values[value_id]=ValueProvenance(old.value_id, str(actual), old.producer_opcode, old.frame_id, old.storage_context, old.pc, old.depth, old.parents)
                    self.shadow_resolved += 1
            elif actual is None or known != actual:
                msg=f"shadow stack value mismatch at pc={log.get('pc')}"
                self.shadow_mismatches.append(msg)
                raise ProvenanceError(msg)
    def _initialize_frame(self, log, frame):
        if frame.initialized:
            return
        if not self.verify_shadow_stack:
            frame.initialized = True
            return
        observed = log.get("stack")
        if not isinstance(observed, list):
            raise ProvenanceError(f"missing concrete stack snapshot at pc={log.get('pc')}")
        if observed and not self.allow_frame_bootstrap:
            raise ProvenanceError(f"frame starts without authenticated stack history at pc={log.get('pc')}")
        frame.stack = [self._new("AUTHENTICATED_FRAME_ENTRY", log, value=str(value)) for value in observed]
        frame.initialized = True
        if observed:
            self.shadow_bootstrapped_frames += 1
    def consume(self,logs):
        for log in logs:
            op=log.get("op")
            if not isinstance(op,str):
                if self.strict: raise ProvenanceError("opcode missing")
                continue
            f=self._frame(log)
            frame_id=log.get("frameId")
            depth=log.get("depth")
            if frame_id not in self.frame_meta:
                self.frame_meta[frame_id]={k: log.get(k) for k in ("caller", "address", "depth", "callTraceIndex", "callInput") if log.get(k) is not None}
                if isinstance(depth, int):
                    self.frame_parent[frame_id]=self._active_frames.get(depth-1)
                    self._active_frames[depth]=frame_id
                    for old_depth in list(self._active_frames):
                        if old_depth > depth:
                            del self._active_frames[old_depth]
            if isinstance(log.get("code"), str) and log["code"]:
                self.frame_code[log["frameId"]]=log["code"]
            self._initialize_frame(log, f)
            self._verify_shadow(log, f)
            self._resolve_pending_branch(log)
            if log.get("returnData") is not None and log.get("returnDataSourceFrame"):
                source_frame=log.get("returnDataSourceFrame")
                source_root=self._frame_return_roots.get(source_frame)
                returned=self._new("RETURNDATA",log,([source_root] if source_root else ()),value=log.get("returnData"))
                f.returndata[0]=returned
            if op.startswith("PUSH"):
                push_value = "0" if op == "PUSH0" else log.get("value")
                f.stack.append(self._new(op,log,value=push_value)); continue
            if op.startswith("DUP"):
                n=int(op[3:]);
                if len(f.stack)<n: raise ProvenanceError(f"DUP{n} underflow")
                f.stack.append(f.stack[-n]); continue
            if op.startswith("SWAP"):
                n=int(op[4:]);
                if len(f.stack)<=n: raise ProvenanceError(f"SWAP{n} underflow")
                f.stack[-1],f.stack[-1-n]=f.stack[-1-n],f.stack[-1]; continue
            if op in self.CALL_ARITY:
                args=self._pop(f.stack,self.CALL_ARITY[op],log); self._observe("external_call",log,args)
                f.stack.append(self._new(op+"_SUCCESS",log,args,log.get("success")))
                continue
            if op in self.UNARY:
                if op in {"ISZERO","NOT"}:
                    parent=self._pop(f.stack,1,log)
                else:
                    parent=[]
                f.stack.append(self._new(op,log,parent,log.get("value"))); continue
            if op in self.ENV_POP_PUSH:
                parent=self._pop(f.stack,1,log)
                f.stack.append(self._new(op,log,parent,log.get("value"))); continue
            if op=="SLOAD":
                if not isinstance(log.get("storageContextAddress"),str): raise ProvenanceError("SLOAD missing storageContextAddress")
                if not isinstance(log.get("frameId"),str): raise ProvenanceError("SLOAD missing frameId")
                slot_parent=self._pop(f.stack,1,log)[0]
                context=str(log["storageContextAddress"]).lower()
                slot=self.values[slot_parent].value or (log.get("stack") or [""])[-1]
                writer=self.last_write.get((context,str(slot).lower()))
                if writer is None:
                    writer=self._new("AUTHENTICATED_PRESTATE",log,[slot_parent])
                f.stack.append(self._new(op,log,[slot_parent,writer])); continue
            if op=="TLOAD":
                slot_parent=self._pop(f.stack,1,log)[0]
                f.stack.append(self._new(op,log,[slot_parent],log.get("value"))); continue
            if op=="TSTORE":
                slot_parent,value_parent=self._pop(f.stack,2,log)
                self._observe("transient_state_write",log,[slot_parent,value_parent]); continue
            if op=="SSTORE":
                if not isinstance(log.get("storageContextAddress"),str): raise ProvenanceError("SSTORE missing storageContextAddress")
                slot_parent,value_parent=self._pop(f.stack,2,log)
                context=str(log["storageContextAddress"]).lower()
                slot=self.values[slot_parent].value or (log.get("stack") or ["", ""])[-1]
                self.last_write[(context,str(slot).lower())]=value_parent
                self._observe("state_write",log,[slot_parent,value_parent]); continue
            if op in {"MSTORE","MSTORE8"}:
                offset,value=self._pop(f.stack,2,log); key=self._int(self.values[offset].value)
                if isinstance(log.get("stack"), list) and len(log["stack"]) >= 2:
                    key = self._int(log["stack"][-1])
                if key is None: raise ProvenanceError(f"non-concrete memory offset at pc={log.get('pc')}")
                f.memory[key]=value; continue
            if op=="MLOAD":
                offset=self._pop(f.stack,1,log)[0]; key=self._int(self.values[offset].value)
                if isinstance(log.get("stack"), list) and log["stack"]:
                    key = self._int(log["stack"][-1])
                if key is None: raise ProvenanceError(f"non-concrete memory offset at pc={log.get('pc')}")
                f.stack.append(self._new(op,log,[f.memory.get(key,offset)])); continue
            if op=="RETURNDATACOPY":
                # EVM stack order is destOffset, offset, size (top first).
                # `_pop` returns top-of-stack first, so preserve that order;
                # reversing these operands silently disconnects returndata
                # from the later MLOAD that consumes it.
                dest_offset,source_offset,size=self._pop(f.stack,3,log)
                source_key=self._int(self.values[source_offset].value)
                dest_key=self._int(self.values[dest_offset].value)
                if source_key is None or dest_key is None:
                    raise ProvenanceError(f"non-concrete returndata/memory offset at pc={log.get('pc')}")
                source=f.returndata.get(source_key)
                if source is None and source_key == 0:
                    source=self._new("RETURNDATA_UNKNOWN",log,value=log.get("returnData",log.get("return_data")))
                    f.returndata[source_key]=source
                if source is not None:
                    f.memory[dest_key]=source
                    self._observe("returndata_copy",log,[size,source])
                else:
                    self._observe("returndata_copy",log,[size])
                continue
            if op in {"CALLDATACOPY","CODECOPY","MCOPY"}:
                self._observe("memory_copy",log,self._pop(f.stack,3,log)); continue
            if op in {"CALLDATALOAD","EXTCODECOPY"}:
                count=1 if op == "CALLDATALOAD" else 4
                parents=self._pop(f.stack,count,log)
                f.stack.append(self._new(op,log,parents,log.get("value"))) if op == "CALLDATALOAD" else None
                continue
            if op in {"KECCAK256"}:
                f.stack.append(self._new(op,log,self._pop(f.stack,2,log))); continue
            if op in {"SIGNEXTEND","EXP","SDIV","SMOD"}:
                f.stack.append(self._new(op,log,self._pop(f.stack,2,log))); continue
            if op in {"CREATE","CREATE2"}:
                f.stack.append(self._new(op,log,self._pop(f.stack,3 if op == "CREATE" else 4,log))); continue
            if op in self.BINARY:
                parents=self._pop(f.stack,3 if op in {"ADDMOD","MULMOD"} else 2,log)
                concrete = None
                if isinstance(log.get("stack"), list):
                    arity = 3 if op in {"ADDMOD","MULMOD"} else 2
                    concrete = [self._int(x) for x in reversed(log["stack"][-arity:])]
                f.stack.append(self._new(op,log,parents,self._computed(op,parents,concrete))); continue
            if op=="ISZERO": f.stack.append(self._new(op,log,self._pop(f.stack,1,log))); continue
            if op=="JUMPI":
                target, condition=self._pop(f.stack,2,log)
                observation=self._observe("branch_predicate",log,[target,condition])
                observation.branch_target=self._int(self.values[target].value)
                self._pending_branches[log.get("frameId")]=observation
                continue
            if op=="JUMP":
                target=self._pop(f.stack,1,log)[0]
                observation=self._observe("jump_target",log,[target])
                observation.branch_target=self._int(self.values[target].value)
                continue
            if op.startswith("LOG"):
                self._observe("event_log",log,self._pop(f.stack,2+int(op[3:] or 0),log)); continue
            if op in {"REVERT", "RETURN"}:
                output_args=self._pop(f.stack,2,log)
                output_kind="FRAME_REVERT_DATA" if op == "REVERT" else "FRAME_RETURN_DATA"
                output_root=self._new(output_kind,log,output_args,log.get("returnData"))
                self._frame_return_roots[log.get("frameId")]=output_root
                self._observe("revert_terminal" if op == "REVERT" else "return_terminal",log,output_args+[output_root])
                continue
            if op in {"POP","STOP","JUMPDEST"}:
                if op=="POP": self._pop(f.stack,1,log)
                continue
            if self.strict: raise ProvenanceError(f"unsupported opcode {op} at pc={log.get('pc')}")
        return self
    def ancestors(self,observation_id):
        obs=next(o for o in self.observations if o.observation_id==observation_id); todo=list(obs.values+obs.parents); seen=set()
        while todo:
            vid=todo.pop()
            if vid in seen or vid not in self.values: continue
            seen.add(vid); todo.extend(self.values[vid].parents)
        return seen
    def to_dict(self): return {"schema_version":"e5-dynamic-provenance-v4","values":[asdict(v) for v in self.values.values()],"observations":[asdict(o) for o in self.observations],"frame_code":self.frame_code,"frame_meta":self.frame_meta,"frame_parent":self.frame_parent,"shadow_stack":{"enabled":self.verify_shadow_stack,"checks":self.shadow_checks,"resolved_values":self.shadow_resolved,"unverified_values":self.shadow_unverified,"bootstrapped_frames":self.shadow_bootstrapped_frames,"mismatches":self.shadow_mismatches,"status":"PASS" if not self.shadow_mismatches and not self.shadow_unverified and not self.shadow_bootstrapped_frames else ("PASS_WITH_BOOTSTRAP" if not self.shadow_mismatches and not self.shadow_unverified else "INCOMPLETE")},"last_writer_count":len(self.last_write)}
