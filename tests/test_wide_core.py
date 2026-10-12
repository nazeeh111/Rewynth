"""Word-width regressions and CPU checks for explicitly owned ARM64 fixtures."""
import ctypes
import hashlib
import json
from pathlib import Path
import platform
import random
import shutil
import subprocess
import tempfile
import unittest
import z3
from native_recovery import recovery_core as core
from native_recovery.inversion import derive_inverse
from native_recovery.artifacts import Artifact
from native_recovery.expression import emit_c

FIXTURES=Path(__file__).parent/'fixtures'
NATIVE=platform.system()=='Darwin' and platform.machine()=='arm64' and shutil.which('clang')


class WideCoreTests(unittest.TestCase):
    def test_exact_word_helpers_and_rejected_widths(self):
        self.assertEqual(core.bv(-1,64).as_long(),(1<<64)-1)
        self.assertEqual(core.signed(1<<63,64),-(1<<63))
        self.assertEqual(core.signed((1<<64)-1,64),-1)
        x=z3.BitVec('x',64)
        self.assertEqual(core.ast_z3(core.constant((1<<64)-1,64),[x]).size(),64)
        for width in [True,16,128]:
            with self.assertRaises(core.Unsupported):core.bv(0,width)
        with self.assertRaises(core.Unsupported):core.ast_z3(core.input_node(0),[x],word_bits=32)
        with self.assertRaises(core.Unsupported):core.ast_z3(core.input_node(0),[x,z3.BitVec('y',32)])
        with self.assertRaises(core.Unsupported):core.ast_z3({'op':'const','value':True},[x])
        with self.assertRaises(core.Unsupported):core.ast_z3({'op':'const','value':1<<64},[x])
        with self.assertRaises(core.Unsupported):core.FunctionModel({},'wrong',1,[x],x,[None],[],[])

    def test_ast_shift_mask_reverse_and_signed_semantics(self):
        x=z3.BitVec('x',64)
        shift={'op':'lshr','a':core.input_node(0),'b':core.constant(64,64)}
        value=core.ast_z3(shift,[x]);self.assertTrue(z3.eq(z3.simplify(value),x))
        reverse=core.ast_z3({'op':'reverse','arg':core.input_node(0),'width':64},[x])
        self.assertEqual(z3.simplify(z3.substitute(reverse,(x,core.bv(1,64)))).as_long(),1<<63)
        one=core.ast_z3({'op':'reverse','arg':core.input_node(0),'width':1},[x])
        self.assertEqual(z3.simplify(z3.substitute(one,(x,core.bv(-1,64)))).as_long(),1)
        compare=core.ast_z3(core.binary('slt',core.input_node(0),core.constant(0,64)),[x])
        self.assertTrue(z3.is_true(z3.simplify(z3.substitute(compare,(x,core.bv(1<<63,64))))))

    def test_from_z3_narrow_width_and_unmasked_shift_boundaries(self):
        x,y=z3.BitVecs('x y',64)
        expressions=[z3.LShR(x,y),x<<y,x>>y,
            z3.ZeroExt(32,z3.Extract(31,0,x)+z3.BitVecVal(1,32)),
            z3.SignExt(32,z3.Extract(31,0,x)),
            z3.ZeroExt(32,z3.RotateRight(z3.Extract(31,0,x),z3.Extract(31,0,y))),
            z3.If(z3.Extract(31,0,x)<z3.BitVecVal(0,32),y,x)]
        for expression in expressions:
            with self.subTest(expression=str(expression)):
                node=core.from_z3(expression,[x,y]);solver=z3.Solver();solver.set(timeout=1000)
                solver.add(expression!=core.ast_z3(node,[x,y]));self.assertEqual(solver.check(),z3.unsat)

    def test_parameterized_model_evidence(self):
        x=z3.BitVec('arg0',64)
        model=core.FunctionModel({'sha256':'owned'},'add',1,[x],x+1,[None],[],[],word_bits=64)
        self.assertEqual(model.evaluate([(1<<64)-1]),0)
        with self.assertRaises(ValueError):model.evaluate([1<<64])
        witness=core.verify_ast(model,core.input_node(0))['counterexample']
        self.assertIn('inputs_u64',witness);self.assertIn('inputs_i64',witness)
        self.assertNotIn('inputs_u32',witness)
        query=core.inverse_query(model,1<<63)
        self.assertEqual(query['status'],'sat');self.assertEqual(query['witness']['output_u64'],1<<63)
        self.assertEqual(model.assumptions()['argument_registers'],['x0'])
        self.assertEqual(model.assumptions()['return_register'],'x0')
        restricted=core.FunctionModel({'sha256':'owned'},'add',1,[x],x+1,[{'min':0,'max':255}],[],[],word_bits=64)
        self.assertEqual(derive_inverse(restricted)['status'],'unsupported_domain')

    def test_real_wide_synthesis_and_inverse_fixture(self):
        for name,arity,domain,grammar in [
            ('wide_mixer',1,None,'lifted_semantics'),('wide_mixed',2,None,'lifted_semantics'),
            ('wide_clamp',1,None,'signed_clamp'),('wide_luma',3,[{'min':0,'max':255}]*3,'affine_u8')]:
            with self.subTest(function=name):
                model=core.load_function(FIXTURES/'wide_kernels.dylib',name,arity,domain,word_bits=64)
                result=core.synthesize(model,grammar,timeout_ms=1000)
                self.assertEqual(result['status'],'verified_model',result)
                self.assertEqual(result['verification']['assumptions']['word_bits'],64)
        model=core.load_function(FIXTURES/'wide_kernels.dylib','wide_mixer',1,word_bits=64)
        inverse=derive_inverse(model,timeout_ms=100)
        self.assertEqual(inverse['status'],'verified_inverse_model',inverse)
        self.assertTrue(any('inverse_constant_u64' in step for step in inverse['chain']))
        self.assertEqual(inverse['proofs']['chain_binding']['status'],'unsat')
        self.assertTrue(all(p['forward_after_inverse']['status']=='unsat' and p['inverse_after_forward']['status']=='unsat' for p in inverse['proofs']['local_two_sided']))
        lossy=core.load_function(FIXTURES/'wide_cpu.dylib','wide_w_zeroext',2,word_bits=64)
        self.assertEqual(derive_inverse(lossy)['status'],'unsupported')
        linear=core.load_function(FIXTURES/'wide_cpu.dylib','wide_linear',3,word_bits=64)
        result=core.synthesize(linear,'gf2_affine',timeout_ms=1000)
        self.assertEqual(result['status'],'verified_model');self.assertEqual(result['oracle_probes'],193)
        reverse=core.load_function(FIXTURES/'wide_cpu.dylib','wide_rbit',1,word_bits=64)
        result=core.synthesize(reverse,'bit_permutation');self.assertEqual(result['status'],'verified_model')
        self.assertEqual(result['parameters']['width'],64)
        # X instructions are never quietly accepted in the default 32-bit model.
        with self.assertRaises(core.Unsupported):core.load_function(FIXTURES/'wide_cpu.dylib','wide_add_shift',1)

    @unittest.skipUnless(NATIVE,'Requires the explicitly selected Mac ARM64 fixture CPU')
    def test_independent_native_isa_and_generated_mixer_programs(self):
        library=ctypes.CDLL(str((FIXTURES/'wide_cpu.dylib').resolve()))
        artifact=Artifact((FIXTURES/'wide_cpu.dylib').read_bytes())
        edges=[0,1,31,32,63,64,65,255,256,4096,0xffffffff,0x100000000,
               0x7fffffffffffffff,0x8000000000000000,0xffffffffffffffff]
        rng=random.Random(1023)
        samples=[[x,y,17,23] for x in edges for y in edges]
        samples.extend([[rng.randrange(1<<64) for _ in range(4)] for _ in range(256)])
        observations=[]
        for symbol in artifact.functions:
            name=symbol.name.removeprefix('_')
            model=core.load_function(FIXTURES/'wide_cpu.dylib',name,4,word_bits=64)
            native=getattr(library,name);native.argtypes=[ctypes.c_uint64]*4;native.restype=ctypes.c_uint64
            for values in samples:self.assertEqual(model.evaluate(values),native(*values),(name,values))
            observations.append({'symbol':name,'native_assertions':len(samples)})
        native_mixer=ctypes.CDLL(str((FIXTURES/'wide_kernels.dylib').resolve())).wide_mixer
        native_mixer.argtypes=[ctypes.c_uint64];native_mixer.restype=ctypes.c_uint64
        mixer=core.load_function(FIXTURES/'wide_kernels.dylib','wide_mixer',1,word_bits=64)
        recovery=core.synthesize(mixer,'lifted_semantics',timeout_ms=1000)
        inverse=derive_inverse(mixer,timeout_ms=100)
        self.assertEqual(recovery['status'],'verified_model');self.assertEqual(inverse['status'],'verified_inverse_model')
        with tempfile.TemporaryDirectory(prefix='rewynth-owned-wide-') as folder:
            folder=Path(folder)
            source=emit_c(recovery['ast'],function_name='forward',argument_count=1,word_bits=64)+emit_c(inverse['ast'],function_name='backward',argument_count=1,word_bits=64)
            (folder/'generated.c').write_text(source)
            subprocess.run(['clang','-O2','-dynamiclib',str(folder/'generated.c'),'-o',str(folder/'generated.dylib')],check=True,capture_output=True)
            generated=ctypes.CDLL(str(folder/'generated.dylib'))
            forward,backward=generated.forward,generated.backward
            for native in [forward,backward]:native.argtypes=[ctypes.c_uint64];native.restype=ctypes.c_uint64
            replay=edges+[rng.randrange(1<<64) for _ in range(2000)]
            for value in replay:
                self.assertEqual(forward(value),native_mixer(value))
                self.assertEqual(backward(native_mixer(value)),value)
                self.assertEqual(native_mixer(backward(value)),value)
            generated_proofs={}
            for name,node in [('forward',recovery['ast']),('backward',inverse['ast'])]:
                try:
                    rebuilt=core.load_function(folder/'generated.dylib',name,1,word_bits=64)
                    proof=core.verify_ast(rebuilt,node,timeout_ms=300)
                    self.assertIn(proof['status'],['unsat','unknown'],proof)
                except core.Unsupported as error:proof={'status':'unavailable','reason':str(error)}
                generated_proofs[name]=proof
            evidence={'isa_artifact_sha256':artifact.digest,'isa_cases':observations,
                      'isa_native_assertions':len(samples)*len(observations),
                      'mixer_function_sha256':mixer.metadata['function_sha256'],
                      'generated_source_sha256':hashlib.sha256(source.encode()).hexdigest(),
                      'generated_artifact_sha256':hashlib.sha256((folder/'generated.dylib').read_bytes()).hexdigest(),
                      'native_mixer_assertions':len(replay)*3,'inverse_proofs':inverse['proofs'],
                      'generated_proofs':generated_proofs}
            (FIXTURES/'wide_final_evidence.json').write_text(json.dumps(evidence,indent=2))


if __name__=='__main__':unittest.main()
