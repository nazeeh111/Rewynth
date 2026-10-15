"""Data-only control-flow fixtures, with explicit instruction encodings."""
import unittest
import z3
from native_recovery import recovery_core as core


class ControlFlowTests(unittest.TestCase):
    def test_two_returns_select_the_executed_path(self):
        # cbz w0,+12; mov w0,#7; ret; mov w0,#9; ret
        model=core.lift_function(bytes.fromhex('60000034e0008052c0035fd620018052c0035fd6'),0,'two_returns',1)
        self.assertEqual(model.evaluate([0]),9)
        self.assertEqual(model.evaluate([1]),7)
        self.assertEqual(model.evaluate([0xffffffff]),7)
        self.assertEqual([r['address'] for r in model.trace([0])],[0,12,16])
        self.assertEqual([r['address'] for r in model.trace([1])],[0,4,8])
        self.assertEqual(model.assumptions()['control_flow']['returns'],2)

    def test_backward_address_edge_is_not_a_cycle(self):
        # cbz w0,+12; add w0,w0,#1; ret; mov w0,#9; b -8
        model=core.lift_function(bytes.fromhex('6000003400040011c0035fd620018052feffff17'),0,'shared_return',1)
        self.assertEqual(model.evaluate([0]),9)
        self.assertEqual(model.evaluate([4]),5)
        self.assertEqual(model.evaluate([0xffffffff]),0)
        self.assertEqual([r['address'] for r in model.trace([0])],[0,12,16,8])
        self.assertEqual(model.trace([0])[-2]['next_address'],8)
        self.assertEqual(model.assumptions()['control_flow']['backward_edges'],1)

    def test_merge_does_not_invent_an_initialized_register(self):
        # cbz w0,+8; mov w1,#5; add w0,w1,#1; ret
        with self.assertRaisesRegex(core.Unsupported,'Uninitialized'):
            core.lift_function(bytes.fromhex('40000034a100805220040011c0035fd6'),0,'undefined_on_one_path',1)

    def test_cycle_and_incomplete_paths_refuse(self):
        for code in ['00000014c0035fd6','40000034c0035fd6','40000014c0035fd6','20000034']:
            with self.subTest(code=code),self.assertRaises(core.Unsupported):
                core.lift_function(bytes.fromhex(code),0,'bad_cfg',1)

    def test_unreachable_tail_preserves_existing_contract(self):
        model=core.lift_function(bytes.fromhex('c0035fd600000000'),0,'identity_with_tail',1)
        self.assertEqual(model.evaluate([27]),27)

    def test_branch_skips_an_unreachable_undecodable_word(self):
        # b +8; unreachable invalid word; add w0,w0,#1; ret
        model=core.lift_function(bytes.fromhex('02000014ffffffff00040011c0035fd6'),0,'gap',1)
        self.assertEqual(model.evaluate([27]),28)
        self.assertEqual([row['address'] for row in model.trace([27])],[0,8,12])

    def test_unsimplified_boolean_inequality_preserves_flag_source(self):
        x,y=z3.BitVecs('flag_x flag_y',32)
        sign_x=z3.Extract(31,31,x)==z3.BitVecVal(1,1)
        sign_y=z3.Extract(31,31,y)==z3.BitVecVal(1,1)
        expression=z3.If(sign_x!=sign_y,x,y)
        ast=core.from_z3(expression,[x,y])
        solver=z3.Solver();solver.add(core.ast_z3(ast,[x,y])!=expression)
        self.assertEqual(solver.check(),z3.unsat)


if __name__=='__main__':unittest.main()
