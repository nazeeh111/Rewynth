/** Pure evaluation of the bounded source AST. No eval, compilation or native code. */
export function evaluate(node, inputs) {
  let count = 0;
  function visit(n, depth) {
    if (++count > 256 || depth > 24 || !n || typeof n !== 'object') throw new Error('Program exceeds evaluation limits.');
    const op = n.op;
    if (op === 'input') { if (!Number.isInteger(n.index) || n.index < 0 || n.index >= inputs.length) throw new Error('Invalid input.'); return inputs[n.index] >>> 0; }
    if (op === 'const') { if (!Number.isInteger(n.value) || n.value < 0 || n.value > 0xffffffff) throw new Error('Invalid constant.'); return n.value; }
    if (op === 'ite') return visit(n.condition, depth+1) ? visit(n.then,depth+1) : visit(n.else,depth+1);
    if (op === 'reverse') { let value = visit(n.arg,depth+1), out = 0; if (!Number.isInteger(n.width) || n.width < 1 || n.width > 32) throw new Error('Invalid reverse width.'); for (let i=0;i<n.width;i++) out = ((out << 1) | ((value >>> i) & 1)) >>> 0; return out; }
    const a = visit(n.a,depth+1), b = visit(n.b,depth+1);
    if (typeof a !== 'number' || typeof b !== 'number') throw new Error('Integer operands required.');
    switch(op) {
      case 'add': return (a+b) >>> 0;
      case 'sub': return (a-b) >>> 0;
      case 'mul': return Math.imul(a,b) >>> 0;
      case 'and': return (a&b) >>> 0;
      case 'or': return (a|b) >>> 0;
      case 'xor': return (a^b) >>> 0;
      case 'shl': return (a << (b&31)) >>> 0;
      case 'lshr': return a >>> (b&31);
      case 'ashr': return ((a|0) >> (b&31)) >>> 0;
      case 'slt': return (a|0) < (b|0);
      case 'sgt': return (a|0) > (b|0);
      case 'ult': return a < b;
      case 'ugt': return a > b;
      case 'eq': return a === b;
      default: throw new Error('Unsupported program operation.');
    }
  }
  const result = visit(node,1);
  if (typeof result !== 'number') throw new Error('Program must return a 32-bit value.');
  return result >>> 0;
}
