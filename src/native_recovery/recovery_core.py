"""Bounded, data-only ARM64 register semantics for explicit 32/64-bit words.

The instruction model is independently tested, not formally verified.
Unsupported memory, calls, branches, extensions and register forms fail closed.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib, time, re
from typing import Any
import capstone
from capstone.arm64 import ARM64_OP_REG, ARM64_OP_IMM
import z3

class Unsupported(ValueError):
    pass

def _word_bits(word_bits):
    if type(word_bits) is not int or word_bits not in (32,64):
        raise Unsupported("word_bits must be exactly 32 or 64")
    return word_bits

def _mask(word_bits):
    return (1 << _word_bits(word_bits))-1

def bv(value, word_bits=32):
    if type(value) is not int:
        raise Unsupported("Bitvector value must be an integer")
    return z3.BitVecVal(value & _mask(word_bits), word_bits)

def signed(value, word_bits=32):
    if type(value) is not int:raise Unsupported("Signed value must be an integer")
    value &= _mask(word_bits)
    return value-(1<<word_bits) if value & (1<<(word_bits-1)) else value

def _infer_word_bits(inputs, word_bits=None):
    if word_bits is None:
        word_bits = inputs[0].size() if inputs and z3.is_bv(inputs[0]) else 32
    _word_bits(word_bits)
    if any(not z3.is_bv(x) or x.size()!=word_bits for x in inputs):
        raise Unsupported("Inputs must all match the selected word width")
    return word_bits

@dataclass
class FunctionModel:
    metadata: dict
    symbol: str
    arity: int
    inputs: list
    expr: Any
    domain: list
    instructions: list
    traces: list
    word_bits: int = 32

    def __post_init__(self):
        _infer_word_bits(self.inputs,self.word_bits)
        if not z3.is_bv(self.expr) or self.expr.size()!=self.word_bits:
            raise Unsupported("Function output must match selected word width")

    def evaluate(self, values):
        if not isinstance(values,(list,tuple)) or len(values)!=self.arity:
            raise ValueError("Wrong argument count")
        if any(type(v) is not int or not -(1<<(self.word_bits-1))<=v<=_mask(self.word_bits) for v in values):
            raise ValueError(f"Inputs must be {self.word_bits}-bit integer values")
        return z3.simplify(z3.substitute(self.expr,*[(x,bv(v,self.word_bits)) for x,v in zip(self.inputs,values)])).as_long()

    def assumptions(self):
        prefix = "x" if self.word_bits==64 else "w"
        return {"architecture":"ARM64","word_bits":self.word_bits,
                "argument_registers":[f"{prefix}{i}" for i in range(self.arity)],
                "return_register":prefix+"0","domain":self.domain,
                "memory":"none; memory instructions rejected","calls":"none; calls rejected",
                "loops":"none; branches rejected in this probe",
                "proof_scope":"output equality in the implemented ISA model; not a formally verified CPU semantics"}

    def constraints(self):
        output=[]
        for x,d in zip(self.inputs,self.domain):
            if d is None: continue
            lo,hi=bv(d["min"],self.word_bits),bv(d["max"],self.word_bits)
            output.extend([x>=lo,x<=hi] if d.get("signed",False) else [z3.UGE(x,lo),z3.ULE(x,hi)])
        return output

    def trace(self, values):
        self.evaluate(values)
        substitutions=[(x,bv(v,self.word_bits)) for x,v in zip(self.inputs,values)]
        output=[]
        for instruction,destination,expr,condition in self.traces:
            item={"address":instruction["address"],"instruction":instruction["assembly"],
                  "destination":destination,f"value_u{self.word_bits}":z3.simplify(z3.substitute(expr,*substitutions)).as_long()}
            if condition is not None:item["condition_taken"]=z3.is_true(z3.simplify(z3.substitute(condition,*substitutions)))
            output.append(item)
        return output

def load_function(path,symbol,arity,domain=None,*,word_bits=32):
    from .artifacts import Artifact, MAX_ARTIFACT
    with Path(path).open("rb") as stream:
        artifact=Artifact(stream.read(MAX_ARTIFACT+1))
    names={f.name for f in artifact.functions}
    selected=symbol if symbol in names else "_"+symbol
    function,code=artifact.function(selected)
    return lift_function(code,function.address,selected,arity,domain,word_bits=word_bits,
                         metadata={"sha256":artifact.digest,"artifact_sha256":artifact.digest,"function_sha256":hashlib.sha256(code).hexdigest()})

def lift_function(code,address,name,arity,domain=None,*,metadata=None,word_bits=32):
    """Lift selected bytes without execution; W writes zero-extend X in 64 mode."""
    _word_bits(word_bits)
    if not isinstance(code,bytes) or not code or len(code)>4096 or len(code)%4:
        raise Unsupported("Function must be 1–4096 aligned bytes")
    if type(address) is not int or address<0 or address%4:
        raise Unsupported("Function address must be a nonnegative aligned integer")
    if type(arity) is not int or not 1<=arity<=4:raise Unsupported("Probe supports 1–4 integer arguments")
    if not isinstance(name,str) or len(name)>1024:raise Unsupported("Bounded function name required")
    if metadata is None:metadata={"sha256":hashlib.sha256(code).hexdigest(),"code_sha256":hashlib.sha256(code).hexdigest(),"identity_scope":"function bytes only"}
    args=[z3.BitVec(f"arg{i}",word_bits) for i in range(arity)]
    # The bank stores full selected words. Reading a W alias extracts low bits;
    # writing W in 64 mode zeroes the corresponding X register's high half.
    bank={i:value for i,value in enumerate(args)}
    engine=capstone.Cs(capstone.CS_ARCH_ARM64,capstone.CS_MODE_LITTLE_ENDIAN);engine.detail=True
    insns=[];traces=[];flags=None;returned=False

    def reg(name):
        match=re.fullmatch(r"([wx])(zr|(?:[0-9]|[12][0-9]|30))",name)
        if not match:raise Unsupported(f"Unsupported register {name}")
        bits=32 if match[1]=="w" else 64
        if bits>word_bits:raise Unsupported("X registers require 64-bit mode")
        return bits,None if match[2]=="zr" else int(match[2])

    def read_register(name):
        bits,index=reg(name)
        if index is None:return bv(0,bits)
        if index not in bank:raise Unsupported(f"Uninitialized register {name}")
        return bank[index] if bits==word_bits else z3.Extract(bits-1,0,bank[index])

    def operand(ins,op,bits):
        if op.ext:raise Unsupported("Extended operands are not supported")
        if op.type==ARM64_OP_IMM:value=bv(op.imm,bits)
        elif op.type==ARM64_OP_REG:
            name=ins.reg_name(op.reg);actual,_=reg(name)
            if actual!=bits:raise Unsupported("Mismatched instruction register widths")
            value=read_register(name)
        else:raise Unsupported("Memory/other operands are not supported")
        shift=op.shift.value
        if op.shift.type:
            if not 0<=shift<bits:raise Unsupported("Invalid shifted operand amount")
            if op.shift.type==capstone.arm64.ARM64_SFT_LSL:value=value<<shift
            elif op.shift.type==capstone.arm64.ARM64_SFT_LSR:value=z3.LShR(value,shift)
            elif op.shift.type==capstone.arm64.ARM64_SFT_ASR:value=value>>shift
            elif op.shift.type==capstone.arm64.ARM64_SFT_ROR:value=z3.RotateRight(value,shift)
            else:raise Unsupported("Unsupported operand shift")
        return value

    constant_cache={}
    constant_nodes={} # Retain DAG nodes while caching IDs; folded temporaries can otherwise recycle IDs.
    def constant_only(value):
        stack=[(value,False)]
        while stack:
            node,expanded=stack.pop();identifier=node.get_id()
            if identifier in constant_cache:continue
            constant_nodes[identifier]=node
            if len(constant_nodes)>32768:raise Unsupported("Constant-fold DAG exceeds resource bound")
            if node.decl().kind()==z3.Z3_OP_UNINTERPRETED:
                constant_cache[identifier]=False
            elif expanded:
                constant_cache[identifier]=all(constant_cache[child.get_id()] for child in node.children())
            else:
                stack.append((node,True))
                stack.extend((child,False) for child in node.children() if child.get_id() not in constant_cache)
        return constant_cache[value.get_id()]

    def arithmetic_flags(a,b,result,subtract=False):
        bits=result.size()
        sa,sb,sr=[z3.Extract(bits-1,bits-1,x)==z3.BitVecVal(1,1) for x in (a,b,result)]
        carry=z3.UGE(a,b) if subtract else z3.ULT(result,a)
        overflow=z3.And(sa!=sb,sr!=sa) if subtract else z3.And(sa==sb,sr!=sa)
        return {"n":sr,"z":result==bv(0,bits),"c":carry,"v":overflow}

    def logical_flags(value):
        return {"n":z3.Extract(value.size()-1,value.size()-1,value)==z3.BitVecVal(1,1),"z":value==bv(0,value.size()),"c":z3.BoolVal(False),"v":z3.BoolVal(False)}

    def condition_code(cc):
        if flags is None:raise Unsupported("Conditional instruction lacks modeled flags")
        n,zero,c,v=[flags[k] for k in ("n","z","c","v")]
        conditions={capstone.arm64.ARM64_CC_EQ:zero,capstone.arm64.ARM64_CC_NE:z3.Not(zero),capstone.arm64.ARM64_CC_HS:c,capstone.arm64.ARM64_CC_LO:z3.Not(c),capstone.arm64.ARM64_CC_HI:z3.And(c,z3.Not(zero)),capstone.arm64.ARM64_CC_LS:z3.Or(z3.Not(c),zero),capstone.arm64.ARM64_CC_GE:n==v,capstone.arm64.ARM64_CC_LT:n!=v,capstone.arm64.ARM64_CC_GT:z3.And(z3.Not(zero),n==v),capstone.arm64.ARM64_CC_LE:z3.Or(zero,n!=v),capstone.arm64.ARM64_CC_MI:n,capstone.arm64.ARM64_CC_PL:z3.Not(n),capstone.arm64.ARM64_CC_VS:v,capstone.arm64.ARM64_CC_VC:z3.Not(v)}
        if cc not in conditions:raise Unsupported("Unsupported condition code")
        return z3.simplify(conditions[cc])

    for ins in engine.disasm(code,address):
        if len(insns)>=128:raise Unsupported("Function exceeds instruction budget")
        if ins.address!=address+4*len(insns):raise Unsupported("Undecoded bytes inside function")
        record={"address":ins.address,"assembly":f"{ins.mnemonic} {ins.op_str}".strip(),"bytes_hex":ins.bytes.hex()};insns.append(record)
        ops=ins.operands;mn=ins.mnemonic;condition=None
        if mn=="ret":
            if ins.op_str:raise Unsupported("Non-default return is unsupported")
            returned=True;break
        if mn in {"cmp","cmn","tst"}:
            if not ops or ops[0].type!=ARM64_OP_REG:raise Unsupported("Flag operation needs register operand")
            bits,_=reg(ins.reg_name(ops[0].reg));a,b=operand(ins,ops[0],bits),operand(ins,ops[1],bits)
            flags=logical_flags(a&b) if mn=="tst" else arithmetic_flags(a,b,a-b if mn=="cmp" else a+b,mn=="cmp")
            continue
        if mn in {"adds","subs","ands"}:mn=mn[:-1]
        if mn not in {"mov","movk","add","sub","mul","madd","msub","and","orr","eor","bic","lsl","lsr","asr","ror","ubfx","bfxil","bfi","rbit","neg","mvn","csel","csinv","csneg","csinc"}:
            raise Unsupported(f"Unsupported instruction {record['assembly']}")
        if not ops or ops[0].type!=ARM64_OP_REG:raise Unsupported("Destination must be a register")
        destination=ins.reg_name(ops[0].reg);bits,index=reg(destination)
        if index is None:raise Unsupported("Zero register destination is not modeled")
        read=lambda i:operand(ins,ops[i],bits)
        if mn=="mov":value=read(1)
        elif mn=="movk":
            if index not in bank:raise Unsupported("MOVK requires an initialized register")
            if ops[1].type!=ARM64_OP_IMM or not 0<=ops[1].imm<=65535 or ops[1].shift.type not in {0,capstone.arm64.ARM64_SFT_LSL} or ops[1].shift.value not in range(0,bits,16):raise Unsupported("Invalid MOVK immediate")
            mask=bv(65535<<ops[1].shift.value,bits);value=(read_register(destination)&~mask)|read(1)
        elif mn=="add":value=read(1)+read(2)
        elif mn=="sub":value=read(1)-read(2)
        elif mn=="mul":value=read(1)*read(2)
        elif mn=="madd":value=read(1)*read(2)+read(3)
        elif mn=="msub":value=read(3)-read(1)*read(2)
        elif mn=="neg":value=-read(1)
        elif mn=="mvn":value=~read(1)
        elif mn=="and":value=read(1)&read(2)
        elif mn=="orr":value=read(1)|read(2)
        elif mn=="eor":value=read(1)^read(2)
        elif mn=="bic":value=read(1)&~read(2)
        elif mn=="lsl":value=read(1)<<(read(2)&bv(bits-1,bits))
        elif mn=="lsr":value=z3.LShR(read(1),read(2)&bv(bits-1,bits))
        elif mn=="asr":value=read(1)>>(read(2)&bv(bits-1,bits))
        elif mn=="ror":value=z3.RotateRight(read(1),read(2)&bv(bits-1,bits))
        elif mn in {"ubfx","bfxil","bfi"}:
            if ops[2].type!=ARM64_OP_IMM or ops[3].type!=ARM64_OP_IMM:raise Unsupported("Bitfield indices must be constant")
            shift,width=ops[2].imm,ops[3].imm
            if not 0<=shift<bits or not 1<=width<=bits-shift:raise Unsupported("Invalid bitfield")
            mask=bv((1<<width)-1,bits);value=z3.LShR(read(1),shift)&mask
            if mn in {"bfxil","bfi"}:
                if index not in bank:raise Unsupported("Bitfield insertion requires an initialized destination")
                if mn=="bfi":
                    mask=mask<<shift;value=(read(1)&bv((1<<width)-1,bits))<<shift
                value=(read_register(destination)&~mask)|value
        elif mn=="rbit":value=z3.Concat(*[z3.Extract(i,i,read(1)) for i in range(bits)])
        else:
            condition=condition_code(ins.cc)
            alternative=~read(2) if mn=="csinv" else -read(2) if mn=="csneg" else read(2)+bv(1,bits) if mn=="csinc" else read(2)
            value=z3.If(condition,read(1),alternative)
        if ins.update_flags:
            if mn in {"add","sub"}:flags=arithmetic_flags(read(1),read(2),value,mn=="sub")
            elif mn=="and":flags=logical_flags(value)
            else:raise Unsupported("Unsupported flag-writing instruction")
        if constant_only(value):value=z3.simplify(value)
        bank[index]=value if bits==word_bits else z3.ZeroExt(word_bits-bits,value)
        traces.append((record,destination,bank[index],condition))
    if not returned or 0 not in bank:raise Unsupported("Missing supported function return")
    domain=[None]*arity if domain is None else domain
    if not isinstance(domain,list) or len(domain)!=arity:raise Unsupported("Domain must have one entry per argument")
    for d in domain:
        if d is None:continue
        if not isinstance(d,dict) or type(d.get("min")) is not int or type(d.get("max")) is not int:raise Unsupported("Integer domain bounds required")
        if set(d)-{"min","max","signed"} or ("signed" in d and type(d["signed"]) is not bool):raise Unsupported("Invalid domain keys or signed flag")
        lo,hi=(-(1<<(word_bits-1)),(1<<(word_bits-1))-1) if d.get("signed",False) else (0,_mask(word_bits))
        if not lo<=d["min"]<=d["max"]<=hi:raise Unsupported("Invalid domain bounds")
    return FunctionModel(metadata,name,arity,args,bank[0],domain,insns,traces,word_bits)

def ast_expr(node, args, depth=0, budget=None, *, word_bits=None):
    W = _infer_word_bits(args, word_bits)
    B = lambda value: bv(value, W)
    if budget is None:
        budget = [0]
    budget[0] += 1
    if depth > 24 or budget[0] > 256:
        raise Unsupported("AST exceeds resource bound")
    if not isinstance(node, dict):
        raise Unsupported("AST node must be an object")
    op = node.get("op")
    if type(op) is not str:
        raise Unsupported("AST operator must be a string")
    schemas = {
        "input": {"op", "index"},
        "const": {"op", "value"},
        "ite": {"op", "condition", "then", "else"},
        "reverse": {"op", "arg", "width"},
    }
    allowed = schemas.get(op, {"op", "a", "b"})
    if set(node) != allowed:
        raise Unsupported("Unexpected or missing AST keys")
    if op == "input":
        i = node.get("index")
        if not type(i) is int or not 0 <= i < len(args):
            raise Unsupported("Invalid input index")
        return args[i]
    if op == "const":
        if not type(node.get("value")) is int or not 0 <= node["value"] <= _mask(W):
            raise Unsupported(f"Constant must be uint{W}")
        return B(node["value"])
    rec = lambda key: ast_expr(node.get(key), args, depth + 1, budget, word_bits=W)
    if op in {
        "add",
        "sub",
        "mul",
        "and",
        "or",
        "xor",
        "lshr",
        "shl",
        "ashr",
        "slt",
        "sgt",
        "ult",
        "ugt",
        "eq",
    }:
        a, b = rec("a"), rec("b")
        if not z3.is_bv(a) or not z3.is_bv(b):
            raise Unsupported("Arithmetic operands must be bitvectors")
        return {
            "add": lambda: a + b,
            "sub": lambda: a - b,
            "mul": lambda: a * b,
            "and": lambda: a & b,
            "or": lambda: a | b,
            "xor": lambda: a ^ b,
            "lshr": lambda: z3.LShR(a, b & B(W - 1)),
            "shl": lambda: a << (b & B(W - 1)),
            "ashr": lambda: a >> (b & B(W - 1)),
            "slt": lambda: a < b,
            "sgt": lambda: a > b,
            "ult": lambda: z3.ULT(a, b),
            "ugt": lambda: z3.UGT(a, b),
            "eq": lambda: a == b,
        }[op]()
    if op == "ite":
        c, t, f = rec("condition"), rec("then"), rec("else")
        if not z3.is_bool(c) or not z3.is_bv(t) or not z3.is_bv(f):
            raise Unsupported("Invalid conditional types")
        return z3.If(c, t, f)
    if op == "reverse":
        a = rec("arg")
        width = node.get("width")
        if not z3.is_bv(a) or not type(width) is int or not 1 <= width <= W:
            raise Unsupported("Invalid reverse width")
        bits = [z3.Extract(i, i, a) for i in range(width)]
        value = bits[0] if width == 1 else z3.Concat(*bits)
        return value if width == W else z3.ZeroExt(W - width, value)
    raise Unsupported(f"Unsupported AST operator {op}")


def input_node(i):
    return {"op": "input", "index": i}


def constant(value, word_bits=32):
    if type(value) is not int: raise Unsupported("Constant value must be an integer")
    return {"op": "const", "value": value & _mask(word_bits)}


def binary(op, a, b):
    return {"op": op, "a": a, "b": b}


def _solver(timeout_ms):
    if not type(timeout_ms) is int or not 1 <= timeout_ms <= 60000:
        raise ValueError("Solver timeout must be 1–60000 ms")
    s = z3.Solver()
    s.set(timeout=timeout_ms)
    return s


def verify_ast(model, ast, timeout_ms=5000):
    W = model.word_bits
    B = lambda value: bv(value, W)
    C = lambda value: constant(value, W)
    S = lambda value: signed(value, W)
    candidate = ast_expr(ast, model.inputs)
    if not z3.is_bv(candidate):
        raise Unsupported(f"Result must be a {W}-bit value")
    solver = _solver(timeout_ms)
    solver.add(*model.constraints(), model.expr != candidate)
    status = solver.check()
    out = {"status": str(status), "assumptions": model.assumptions()}
    if status == z3.sat:
        m = solver.model()
        values = [m.eval(x, model_completion=True).as_long() for x in model.inputs]
        other = z3.simplify(
            z3.substitute(
                candidate, *[(x, B(v)) for x, v in zip(model.inputs, values)]
            )
        ).as_long()
        out["counterexample"] = {
            f"inputs_u{W}": values,
            f"inputs_i{W}": [S(v) for v in values],
            f"original_output_u{W}": model.evaluate(values),
            f"candidate_output_u{W}": other,
            "trace": model.trace(values),
        }
    elif status == z3.unknown:
        out["reason"] = solver.reason_unknown()
    return out


def inverse_query(model, target, timeout_ms=5000):
    W = model.word_bits
    B = lambda value: bv(value, W)
    C = lambda value: constant(value, W)
    S = lambda value: signed(value, W)
    if not type(target) is int or not 0 <= target <= _mask(W):
        raise ValueError(f"Target must be uint{W}")
    solver = _solver(timeout_ms)
    solver.add(*model.constraints(), model.expr == B(target))
    status = solver.check()
    out = {
        "status": str(status),
        f"target_u{W}": target,
        "assumptions": model.assumptions(),
    }
    if status == z3.sat:
        m = solver.model()
        values = [m.eval(x, model_completion=True).as_long() for x in model.inputs]
        out["witness"] = {
            f"inputs_u{W}": values,
            f"inputs_i{W}": [S(v) for v in values],
            f"output_u{W}": model.evaluate(values),
            "trace": model.trace(values),
        }
    elif status == z3.unknown:
        out["reason"] = solver.reason_unknown()
    return out


def _samples(model):
    W = model.word_bits
    B = lambda value: bv(value, W)
    C = lambda value: constant(value, W)
    S = lambda value: signed(value, W)
    seeds = [
        0,
        1,
        2,
        127,
        128,
        255,
        256,
        65535,
        65536,
        (1 << (W - 1)) - 1,
        1 << (W - 1),
        _mask(W),
    ]
    if model.arity == 1:
        values = [[x] for x in seeds]
    else:
        values = [[0] * model.arity]
    for i in range(model.arity):
        for x in seeds[:8]:
            row = [0] * model.arity
            row[i] = x
            values.append(row)
    values.extend([[255] * model.arity, list(range(1, model.arity + 1))])
    return [
        v
        for v in values
        if all(
            d is None
            or d["min"] <= (S(x) if d.get("signed", False) else x) <= d["max"]
            for x, d in zip(v, model.domain)
        )
    ]


def _synthesize_clamp(model, timeout_ms, max_rounds):
    W = model.word_bits
    B = lambda value: bv(value, W)
    C = lambda value: constant(value, W)
    S = lambda value: signed(value, W)
    if model.arity != 1:
        return None
    lo, hi = z3.BitVecs("clamp_low clamp_high", W)
    solver = _solver(timeout_ms)
    solver.add(lo >= B(-65536), hi <= B(65536), lo <= hi)
    expression = lambda x: z3.If(x < lo, lo, z3.If(x > hi, hi, x))
    samples = _samples(model)
    counterexamples = []
    for sample in samples:
        solver.add(expression(B(sample[0])) == B(model.evaluate(sample)))
    for round_no in range(max_rounds):
        status = solver.check()
        if status != z3.sat:
            return (
                None
                if status == z3.unsat
                else {
                    "status": "unknown",
                    "reason": solver.reason_unknown(),
                    "grammar": "signed_clamp",
                }
            )
        m = solver.model()
        low = m.eval(lo).as_long()
        high = m.eval(hi).as_long()
        x = input_node(0)
        ast = {
            "op": "ite",
            "condition": binary("slt", x, C(low)),
            "then": C(low),
            "else": {
                "op": "ite",
                "condition": binary("sgt", x, C(high)),
                "then": C(high),
                "else": x,
            },
        }
        result = verify_ast(model, ast, timeout_ms)
        if result["status"] == "unsat":
            return {
                "status": "verified_model",
                "grammar": "signed_clamp",
                "ast": ast,
                "parameters": {f"low_i{W}": S(low), f"high_i{W}": S(high)},
                "rounds": round_no + 1,
                "counterexamples": counterexamples,
                "verification": result,
            }
        if result["status"] == "unknown":
            return {
                "status": "unknown",
                "grammar": "signed_clamp",
                "reason": result.get("reason"),
                "counterexamples": counterexamples,
            }
        witness = result["counterexample"]
        counterexamples.append(witness)
        values = witness[f"inputs_u{W}"]
        solver.add(expression(B(values[0])) == B(witness[f"original_output_u{W}"]))
    return {
        "status": "exhausted",
        "grammar": "signed_clamp",
        "counterexamples": counterexamples,
    }


def _synthesize_reverse(model, timeout_ms, max_rounds):
    W = model.word_bits
    B = lambda value: bv(value, W)
    C = lambda value: constant(value, W)
    S = lambda value: signed(value, W)
    if model.arity != 1:
        return None
    observations = [model.evaluate([1 << i]) for i in range(W)]
    if model.evaluate([0]) != 0:
        return None
    for width in range(1, W + 1):
        if observations != [
            1 << (width - 1 - i) if i < width else 0 for i in range(W)
        ]:
            continue
        ast = {"op": "reverse", "arg": input_node(0), "width": width}
        result = verify_ast(model, ast, timeout_ms)
        return {
            "status": "verified_model"
            if result["status"] == "unsat"
            else result["status"],
            "grammar": "bit_permutation",
            "ast": ast,
            "parameters": {"width": width},
            "rounds": 1,
            "counterexamples": [],
            "verification": result,
            "oracle_probes": W + 1,
        }
    return None


def _synthesize_affine(model, timeout_ms, max_rounds):
    W = model.word_bits
    B = lambda value: bv(value, W)
    C = lambda value: constant(value, W)
    S = lambda value: signed(value, W)
    if model.arity != 3:
        return None
    coefficients = [z3.BitVec(f"coefficient{i}", W) for i in range(3)]
    shift = z3.BitVec("shift", W)
    solver = _solver(timeout_ms)
    solver.add(z3.ULE(shift, B(16)))
    for c in coefficients:
        solver.add(z3.ULE(c, B(255)))
    expression = lambda xs: (
        z3.LShR(sum([c * x for c, x in zip(coefficients, xs)], B(0)), shift) & B(255)
    )
    for sample in _samples(model):
        solver.add(expression([B(v) for v in sample]) == B(model.evaluate(sample)))
    counterexamples = []
    for round_no in range(max_rounds):
        status = solver.check()
        if status != z3.sat:
            return (
                None
                if status == z3.unsat
                else {
                    "status": "unknown",
                    "reason": solver.reason_unknown(),
                    "grammar": "affine_u8",
                }
            )
        m = solver.model()
        cs = [m.eval(c).as_long() for c in coefficients]
        s = m.eval(shift).as_long()
        value = binary("mul", input_node(0), C(cs[0]))
        for i in range(1, 3):
            value = binary("add", value, binary("mul", input_node(i), C(cs[i])))
        ast = binary("and", binary("lshr", value, C(s)), C(255))
        result = verify_ast(model, ast, timeout_ms)
        if result["status"] == "unsat":
            return {
                "status": "verified_model",
                "grammar": "affine_u8",
                "ast": ast,
                "parameters": {"coefficients": cs, "shift": s},
                "rounds": round_no + 1,
                "counterexamples": counterexamples,
                "verification": result,
            }
        if result["status"] == "unknown":
            return {
                "status": "unknown",
                "reason": result.get("reason"),
                "grammar": "affine_u8",
                "counterexamples": counterexamples,
            }
        witness = result["counterexample"]
        counterexamples.append(witness)
        solver.add(
            expression([B(v) for v in witness[f"inputs_u{W}"]])
            == B(witness[f"original_output_u{W}"])
        )
    return {
        "status": "exhausted",
        "grammar": "affine_u8",
        "counterexamples": counterexamples,
    }


def synthesize(model, grammar="auto", timeout_ms=5000, max_rounds=32):
    if not type(max_rounds) is int or not 1 <= max_rounds <= 128:
        raise ValueError("Round budget must be 1–128")
    methods = {
        "signed_clamp": _synthesize_clamp,
        "bit_permutation": _synthesize_reverse,
        "affine_u8": _synthesize_affine,
        "gf2_affine": _synthesize_gf2,
        "lifted_semantics": _synthesize_general,
    }
    if grammar != "auto" and grammar not in methods:
        raise Unsupported("Unknown synthesis grammar")
    started = time.monotonic()
    refinement = []
    for name, method in methods.items():
        if grammar != "auto" and name != grammar:
            continue
        result = method(model, timeout_ms, max_rounds)
        if (
            result is not None
            and result.get("status") == "not_affine"
            and grammar == "auto"
        ):
            refinement.extend(result.get("counterexamples", []))
            continue
        if (
            result is not None
            and result.get("status") in {"unknown", "exhausted"}
            and grammar == "auto"
        ):
            refinement.extend(result.get("counterexamples", []))
            continue
        if result is not None:
            result["counterexamples"] = refinement + result.get("counterexamples", [])
            result.update(
                {
                    "symbol": model.symbol,
                    "artifact_sha256": model.metadata["sha256"],
                    "elapsed_seconds": time.monotonic() - started,
                }
            )
            return result
    return {
        "status": "outside_grammar",
        "symbol": model.symbol,
        "elapsed_seconds": time.monotonic() - started,
        "reason": "No supported grammar fits the observed kernel; no reconstruction claimed",
    }


def expression_to_ast(expr, inputs, *, word_bits=None):
    """Translate supported lifted bitvector semantics to the editable safe DSL.

    Narrow temporaries are explicitly masked/sign-extended, preserving machine
    width semantics rather than interpreting extracted bits as C signed ints.
    """
    if word_bits is None:
        word_bits = expr.size() if z3.is_bv(expr) and expr.size() in (32,64) else (inputs[0].size() if inputs else 32)
    W = _infer_word_bits(inputs, word_bits)
    C = lambda value: constant(value, W)
    input_ids = {x.get_id(): i for i, x in enumerate(inputs)}
    conversion_visits = [0]
    variable_dependencies = {}
    def has_variable(n):
        stack=[(n,False)]
        while stack:
            node,expanded=stack.pop();identifier=node.get_id()
            if identifier in variable_dependencies:continue
            if len(variable_dependencies)>32768:raise Unsupported("Constant-fold analysis exceeds expression budget")
            if node.decl().kind()==z3.Z3_OP_UNINTERPRETED:variable_dependencies[identifier]=True
            elif expanded:variable_dependencies[identifier]=any(variable_dependencies[child.get_id()] for child in node.children())
            else:
                stack.append((node,True))
                stack.extend((child,False) for child in node.children() if child.get_id() not in variable_dependencies)
        return variable_dependencies[n.get_id()]

    def boolean_value(n):
        return {
            "op": "ite",
            "condition": convert(n),
            "then": C(1),
            "else": C(0),
        }

    def sign_extended(ast, width):
        if width == W:
            return ast
        return binary(
            "ashr", binary("shl", ast, C(W - width)), C(W - width)
        )

    def convert(n):
        conversion_visits[0] += 1
        if conversion_visits[0] > 256:
            raise Unsupported("Expression expansion exceeds editable resource bound")
        if n.get_id() in input_ids:
            return input_node(input_ids[n.get_id()])
        if z3.is_bv_value(n):
            if n.size()>W:raise Unsupported("Constant exceeds selected word width")
            return C(n.as_long())
        if not has_variable(n):
            reduced=z3.simplify(n)
            if z3.is_bv_value(reduced):
                if reduced.size()>W:raise Unsupported("Constant exceeds selected word width")
                return C(reduced.as_long())
            if z3.is_true(reduced):return binary("eq",C(0),C(0))
            if z3.is_false(reduced):return binary("eq",C(0),C(1))
        if z3.is_true(n):
            return binary("eq", C(0), C(0))
        if z3.is_false(n):
            return binary("eq", C(0), C(1))
        if z3.is_bv(n) and n.size() > W:
            raise Unsupported("Expression exceeds the selected word width")
        kind = n.decl().kind()
        children = list(n.children())
        if kind == z3.Z3_OP_ITE:
            if z3.is_bool(n):
                return binary(
                    "eq",
                    {
                        "op": "ite",
                        "condition": convert(children[0]),
                        "then": boolean_value(children[1]),
                        "else": boolean_value(children[2]),
                    },
                    C(1),
                )
            return {
                "op": "ite",
                "condition": convert(children[0]),
                "then": convert(children[1]),
                "else": convert(children[2]),
            }
        if kind == z3.Z3_OP_NOT:
            return binary("eq", boolean_value(children[0]), C(0))
        if kind in {z3.Z3_OP_AND, z3.Z3_OP_OR, z3.Z3_OP_XOR}:
            values = [boolean_value(child) for child in children]
            op = {z3.Z3_OP_AND: "and", z3.Z3_OP_OR: "or", z3.Z3_OP_XOR: "xor"}[kind]
            out = values[0]
            for child in values[1:]:
                out = binary(op, out, child)
            return binary("eq", out, C(1))
        comparisons = {
            z3.Z3_OP_EQ: "eq",
            z3.Z3_OP_ULT: "ult",
            z3.Z3_OP_UGT: "ugt",
            z3.Z3_OP_SLT: "slt",
            z3.Z3_OP_SGT: "sgt",
        }
        if kind in comparisons:
            a, b = children
            aa, bb = (
                (boolean_value(a), boolean_value(b))
                if z3.is_bool(a)
                else (convert(a), convert(b))
            )
            if kind in {z3.Z3_OP_SLT, z3.Z3_OP_SGT}:
                aa, bb = sign_extended(aa, a.size()), sign_extended(bb, b.size())
            return binary(comparisons[kind], aa, bb)
        inverse_comparisons = {
            z3.Z3_OP_ULEQ: "ugt",
            z3.Z3_OP_UGEQ: "ult",
            z3.Z3_OP_SLEQ: "sgt",
            z3.Z3_OP_SGEQ: "slt",
        }
        if kind in inverse_comparisons:
            a, b = children
            aa, bb = convert(a), convert(b)
            if kind in {z3.Z3_OP_SLEQ, z3.Z3_OP_SGEQ}:
                aa, bb = sign_extended(aa, a.size()), sign_extended(bb, b.size())
            inner = binary(inverse_comparisons[kind], aa, bb)
            return binary(
                "eq",
                {
                    "op": "ite",
                    "condition": inner,
                    "then": C(1),
                    "else": C(0),
                },
                C(0),
            )
        if kind == z3.Z3_OP_EXTRACT:
            hi, lo = n.params()
            value = convert(children[0])
            width = hi - lo + 1
            return binary(
                "and", binary("lshr", value, C(lo)), C((1 << width) - 1)
            )
        if kind == z3.Z3_OP_ZERO_EXT:
            return convert(children[0])
        if kind == z3.Z3_OP_SIGN_EXT:
            return binary(
                "and",
                sign_extended(convert(children[0]), children[0].size()),
                C((1 << n.size()) - 1),
            )
        if kind == z3.Z3_OP_CONCAT:
            out = convert(children[0])
            for child in children[1:]:
                out = binary(
                    "or", binary("shl", out, C(child.size())), convert(child)
                )
            return out
        if kind in {z3.Z3_OP_EXT_ROTATE_RIGHT, z3.Z3_OP_EXT_ROTATE_LEFT}:
            a, b = map(convert, children)
            operation_width=n.size()
            b=binary("and",b,C(operation_width-1))
            op1,op2=("lshr","shl") if kind==z3.Z3_OP_EXT_ROTATE_RIGHT else ("shl","lshr")
            out=binary("or",binary(op1,a,b),binary(op2,a,binary("sub",C(operation_width),b)))
            return binary("and",out,C((1<<operation_width)-1)) if operation_width<W else out
        operations = {
            z3.Z3_OP_BADD: "add",
            z3.Z3_OP_BSUB: "sub",
            z3.Z3_OP_BMUL: "mul",
            z3.Z3_OP_BAND: "and",
            z3.Z3_OP_BOR: "or",
            z3.Z3_OP_BXOR: "xor",
            z3.Z3_OP_BSHL: "shl",
            z3.Z3_OP_BLSHR: "lshr",
            z3.Z3_OP_BASHR: "ashr",
        }
        if kind in operations:
            values = [convert(child) for child in children]
            if kind == z3.Z3_OP_BASHR:
                values[0] = sign_extended(values[0], children[0].size())
            out = values[0]
            for value in values[1:]:
                out = binary(operations[kind], out, value)
            if n.size()<W:out=binary("and",out,C((1<<n.size())-1))
            if kind in {z3.Z3_OP_BSHL,z3.Z3_OP_BLSHR,z3.Z3_OP_BASHR}:
                amount=z3.simplify(children[1]);limit=n.size()
                if z3.is_bv_value(amount) and amount.as_long()<limit:return out
                fill=C(0) if kind!=z3.Z3_OP_BASHR else binary("and",binary("ashr",sign_extended(convert(children[0]),limit),C(W-1)),C((1<<limit)-1))
                if z3.is_bv_value(amount):return fill
                return {"op":"ite","condition":binary("ult",convert(children[1]),C(limit)),"then":out,"else":fill}
            return out
        if kind == z3.Z3_OP_BNOT:
            return binary("xor", convert(children[0]), C((1 << n.size()) - 1))
        if kind == z3.Z3_OP_BNEG:
            out = binary("sub", C(0), convert(children[0]))
            return (
                binary("and", out, C((1 << n.size()) - 1))
                if n.size() < W
                else out
            )
        raise Unsupported(
            f"Lifted expression operator outside editable DSL: {n.decl().name()}"
        )

    ast = convert(expr)
    ast_expr(ast, inputs, word_bits=W)  # enforce final types, depth and size
    return ast


def _synthesize_gf2(model, timeout_ms, max_rounds):
    W = model.word_bits
    B = lambda value: bv(value, W)
    C = lambda value: constant(value, W)
    S = lambda value: signed(value, W)
    """Infer an affine binary map from basis vectors, compress masks and shifts.

    GF(2) means each output bit is an XOR of input bits and a constant bit.
    Basis observations only propose the map; the solver checks all domain inputs.
    """
    zeros = [0] * model.arity
    offset = model.evaluate(zeros)
    groups = {}
    for index in range(model.arity):
        for bit in range(W):
            values = zeros.copy()
            values[index] = 1 << bit
            result = model.evaluate(values) ^ offset
            for outbit in range(W):
                if (result >> outbit) & 1:
                    key = (index, outbit - bit)
                    groups[key] = groups.get(key, 0) | (1 << bit)
    nodes = []
    if offset:
        nodes.append(C(offset))
    for (index, shift), mask in sorted(groups.items()):
        node = input_node(index)
        if mask != _mask(W):
            node = binary("and", node, C(mask))
        if shift:
            node = binary("shl" if shift > 0 else "lshr", node, C(abs(shift)))
        nodes.append(node)
    ast = C(0) if not nodes else nodes[0]
    for node in nodes[1:]:
        ast = binary("xor", ast, node)
    try:
        ast_expr(ast, model.inputs)
    except Unsupported:
        return None
    verification = verify_ast(model, ast, timeout_ms)
    if verification["status"] == "unsat":
        return {
            "status": "verified_model",
            "grammar": "gf2_affine",
            "ast": ast,
            "rounds": 1,
            "oracle_probes": 1 + W * model.arity,
            "shift_mask_groups": len(groups),
            "counterexamples": [],
            "verification": verification,
        }
    return {
        "status": "not_affine",
        "grammar": "gf2_affine",
        "counterexamples": [verification["counterexample"]]
        if verification["status"] == "sat"
        else [],
        "verification": verification,
    }


def _synthesize_general(model, timeout_ms, max_rounds):
    W = model.word_bits
    B = lambda value: bv(value, W)
    C = lambda value: constant(value, W)
    S = lambda value: signed(value, W)
    try:
        ast = expression_to_ast(model.expr, model.inputs, word_bits=W)
    except Unsupported as error:
        return {
            "status": "outside_editable_limits",
            "grammar": "lifted_semantics",
            "reason": str(error),
        }
    verification = verify_ast(model, ast, timeout_ms)
    return {
        "status": "verified_model"
        if verification["status"] == "unsat"
        else verification["status"],
        "grammar": "lifted_semantics",
        "ast": ast,
        "rounds": 1,
        "counterexamples": [verification["counterexample"]]
        if verification["status"] == "sat"
        else [],
        "verification": verification,
    }


def ast_z3(node, inputs, word_bits=None):
    return ast_expr(node, inputs, word_bits=word_bits)


def from_z3(expr, inputs, word_bits=None):
    return expression_to_ast(expr, inputs, word_bits=word_bits)
