/** Exact bounded word evaluation. BigInt preserves every bit; no eval or native code. */
function integer(value) {
  if (typeof value === 'bigint') return value;
  if (typeof value === 'number' && Number.isSafeInteger(value)) return BigInt(value);
  if (typeof value === 'string' && value.length <= 80 && /^-?(?:0x[0-9a-f]+|[0-9]+)$/i.test(value)) {
    return value.startsWith('-') ? -BigInt(value.slice(1)) : BigInt(value);
  }
  throw new Error('An exact integer value is required.');
}
export function evaluate(node, inputs, wordBits = 32) {
  if (wordBits !== 32 && wordBits !== 64) throw new Error('Word size must be 32 or 64 bits.');
  const bits = BigInt(wordBits), mask = (1n << bits) - 1n, shiftMask = bits - 1n;
  const signed = value => value >= (1n << (bits-1n)) ? value - (1n << bits) : value;
  const checked = value => { const n = integer(value); if (n < 0n || n > mask) throw new Error('Word is outside the selected unsigned range.'); return n; };
  if (!Array.isArray(inputs) || inputs.length < 1 || inputs.length > 4) throw new Error('One to four inputs required.');
  inputs.forEach(checked);
  let count = 0;
  const comparisons = ['slt','sgt','ult','ugt','eq'];
  function validate(n, depth) {
    if (++count > 256 || depth > 24 || !n || typeof n !== 'object' || Array.isArray(n)) throw new Error('Program exceeds evaluation limits.');
    const op = n.op;
    const fields = op === 'input' ? ['op','index'] : op === 'const' ? ['op','value'] : op === 'reverse' ? ['op','arg','width'] : op === 'ite' ? ['op','condition','then','else'] : ['op','a','b'];
    if (Object.keys(n).length !== fields.length || fields.some(key => !Object.hasOwn(n,key))) throw new Error('Invalid program fields.');
    if (op === 'input') { if (!Number.isInteger(n.index) || n.index < 0 || n.index >= inputs.length) throw new Error('Invalid input.'); return 'word'; }
    if (op === 'const') { checked(n.value); return 'word'; }
    if (op === 'reverse') { if (!Number.isInteger(n.width) || n.width < 1 || n.width > wordBits || validate(n.arg,depth+1) !== 'word') throw new Error('Invalid reversal.'); return 'word'; }
    if (op === 'ite') { if (validate(n.condition,depth+1) !== 'bool' || validate(n.then,depth+1) !== 'word' || validate(n.else,depth+1) !== 'word') throw new Error('Invalid conditional.'); return 'word'; }
    if (!['add','sub','mul','and','or','xor','shl','lshr','ashr',...comparisons].includes(op) || validate(n.a,depth+1) !== 'word' || validate(n.b,depth+1) !== 'word') throw new Error('Invalid operation operands.');
    return comparisons.includes(op) ? 'bool' : 'word';
  }
  if (validate(node,1) !== 'word') throw new Error('Program must return an integer word.');
  function visit(n, depth) {
    const op = n.op;
    if (op === 'input') { if (!Number.isInteger(n.index) || n.index < 0 || n.index >= inputs.length) throw new Error('Invalid input.'); return checked(inputs[n.index]); }
    if (op === 'const') return checked(n.value);
    if (op === 'ite') { const condition = visit(n.condition,depth+1); if (typeof condition !== 'boolean') throw new Error('Boolean condition required.'); return visit(condition ? n.then : n.else,depth+1); }
    if (op === 'reverse') {
      const value = visit(n.arg,depth+1); let out = 0n;
      if (typeof value !== 'bigint' || !Number.isInteger(n.width) || n.width < 1 || n.width > wordBits) throw new Error('Invalid reversal.');
      for (let i=0n; i<BigInt(n.width); i++) out = (out << 1n) | ((value >> i) & 1n);
      return out;
    }
    const a = visit(n.a,depth+1), b = visit(n.b,depth+1);
    if (typeof a !== 'bigint' || typeof b !== 'bigint') throw new Error('Integer operands required.');
    switch(op) {
      case 'add': return (a+b) & mask;
      case 'sub': return (a-b) & mask;
      case 'mul': return (a*b) & mask;
      case 'and': return a&b;
      case 'or': return a|b;
      case 'xor': return a^b;
      case 'shl': return (a << (b&shiftMask)) & mask;
      case 'lshr': return a >> (b&shiftMask);
      case 'ashr': return (signed(a) >> (b&shiftMask)) & mask;
      case 'slt': return signed(a) < signed(b);
      case 'sgt': return signed(a) > signed(b);
      case 'ult': return a < b;
      case 'ugt': return a > b;
      case 'eq': return a === b;
      default: throw new Error('Unsupported program operation.');
    }
  }
  const result = visit(node,1);
  if (typeof result !== 'bigint') throw new Error('Program must return an integer word.');
  return wordBits === 32 ? Number(result) : result;
}
