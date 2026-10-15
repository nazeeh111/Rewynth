"""Bounded reachable ARM64 control-flow structure, without executing bytes."""
from dataclasses import dataclass
import heapq
import capstone
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_REG


class ControlFlowError(ValueError):
    pass


@dataclass(frozen=True)
class Branch:
    kind: str
    target: int
    fallthrough: int | None
    register: str | None = None
    bit: int | None = None


@dataclass
class Graph:
    instructions: dict
    successors: dict
    branches: dict
    order: list

    def summary(self):
        return {"kind":"acyclic_direct", "instructions":len(self.instructions),
                "edges":sum(len(v) for v in self.successors.values()),
                "branches":len(self.branches),
                "returns":sum(ins.mnemonic=='ret' for ins in self.instructions.values()),
                "backward_edges":sum(b<a for a,values in self.successors.items() for b in values),
                "instruction_limit":128,"edge_limit":256}


def decode_graph(code, address):
    engine=capstone.Cs(capstone.CS_ARCH_ARM64,capstone.CS_MODE_LITTLE_ENDIAN)
    engine.detail=True
    reachable,successors,branches={}, {}, {}
    pending=[address]
    while pending:
        pc=pending.pop()
        if pc in reachable:continue
        if not address<=pc<address+len(code) or (pc-address)%4:
            raise ControlFlowError("Control flow leaves decoded function bounds")
        if len(reachable)>=128:
            raise ControlFlowError("Function exceeds reachable instruction budget")
        offset=pc-address
        ins=next(engine.disasm(code[offset:offset+4],pc,count=1),None)
        if ins is None or ins.size!=4:
            raise ControlFlowError("Undecoded bytes on a reachable function path")
        reachable[pc]=ins
        mn=ins.mnemonic;ops=ins.operands
        def target(index):
            if len(ops)<=index or ops[index].type!=ARM64_OP_IMM:
                raise ControlFlowError("Direct branch target required")
            return ops[index].imm
        branch=None
        if mn=='ret':
            if ins.op_str:raise ControlFlowError("Non-default return is unsupported")
            edges=[]
        elif mn=='b':
            if len(ops)!=1:raise ControlFlowError("Invalid unconditional branch")
            branch=Branch('always',target(0),None)
        elif mn.startswith('b.'):
            if len(ops)!=1:raise ControlFlowError("Invalid conditional branch")
            always=ins.cc in (capstone.arm64.ARM64_CC_AL,capstone.arm64.ARM64_CC_NV)
            branch=Branch('always' if always else 'flags',target(0),None if always else pc+4)
        elif mn in ('cbz','cbnz','tbz','tbnz'):
            count=3 if mn.startswith('tb') else 2
            if len(ops)!=count or ops[0].type!=ARM64_OP_REG:
                raise ControlFlowError("Invalid compare/test branch operands")
            bit=None
            if count==3:
                if ops[1].type!=ARM64_OP_IMM:raise ControlFlowError("Constant branch bit required")
                bit=ops[1].imm
            branch=Branch(mn,target(count-1),pc+4,ins.reg_name(ops[0].reg),bit)
        else:
            edges=[pc+4]
        if branch:
            branches[pc]=branch
            edges=[branch.target] if branch.fallthrough is None else [branch.target,branch.fallthrough]
        edges=list(dict.fromkeys(edges))
        successors[pc]=edges
        if sum(len(v) for v in successors.values())>256:
            raise ControlFlowError("Function exceeds control-flow edge budget")
        pending.extend(edges)
    # Numerical backward edges are legal in an acyclic compiler layout. Kahn's
    # ordering rejects actual graph cycles, including paths that might be infeasible.
    degree={pc:0 for pc in reachable}
    for edges in successors.values():
        for pc in edges:degree[pc]+=1
    ready=[pc for pc,n in degree.items() if n==0];heapq.heapify(ready)
    order=[]
    while ready:
        pc=heapq.heappop(ready);order.append(pc)
        for after in successors[pc]:
            degree[after]-=1
            if degree[after]==0:heapq.heappush(ready,after)
    if len(order)!=len(reachable):
        raise ControlFlowError("Cyclic control flow / loops are unsupported")
    return Graph(reachable,successors,branches,order)
