"""Source-bound witness replay with the retained public PCG object."""
import copy
import json
from pathlib import Path
import unittest
import tempfile
import os
from unittest.mock import patch
from native_recovery.artifacts import Artifact
from native_recovery.engine import run_operation
from native_recovery.witness import create, replay, digest, publish_exclusive, capture_witness

class MemoryWitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        artifact=Artifact((Path(__file__).parents[1]/'src/native_recovery/resources/examples/pcg-basic.o').read_bytes())
        fn,code=artifact.function('_pcg32_random_r')
        cls.artifact,cls.fn,cls.code=artifact,fn,code
        settings={'artifact':artifact.digest,'arity':1,'word_bits':64,'memory':{'argument':0,'words':2}}
        original=run_operation({**settings,'operation':'recover'},code,fn.address,fn.name)
        edited=json.loads(original['expression']);edited['memory'][0]='x0'
        cls.request={**settings,'operation':'verify','expression':json.dumps(edited)}
        result=run_operation(cls.request,code,fn.address,fn.name)
        cls.record=create(cls.request,code,fn.address,fn.name,result,run_operation)

    def test_replay_and_independent_state_oracle(self):
        result=replay(self.record,self.artifact.digest,self.code,self.fn.address,self.fn.name,run_operation)['observation']
        exact=lambda v:int(v,0) if isinstance(v,str) else v
        state,inc=map(exact,result['inputs_u64'])
        self.assertEqual(exact(result['original_memory_u64'][0]),(state*6364136223846793005+inc)&((1<<64)-1))
        self.assertEqual(exact(result['candidate_memory_u64'][0]),state)
        self.assertEqual(result['differences'],['memory[0]'])
        self.assertEqual(result['original_output_u64'],result['candidate_output_u64'])
        self.assertEqual(result['original_memory_u64'][1],result['candidate_memory_u64'][1])

    def test_changed_or_rehashed_observations_refuse(self):
        for field in ('artifact_sha256','function_sha256','c_harness'):
            bad=copy.deepcopy(self.record);bad['payload'][field]='changed';bad['sha256']=digest(bad['payload'])
            with self.subTest(field=field),self.assertRaises(ValueError):replay(bad,self.artifact.digest,self.code,self.fn.address,self.fn.name,run_operation)
        bad=copy.deepcopy(self.record);bad['payload']['observation']['differences']=[];bad['sha256']=digest(bad['payload'])
        with self.assertRaises(ValueError):replay(bad,self.artifact.digest,self.code,self.fn.address,self.fn.name,run_operation)

    def test_publication_failure_preserves_existing_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'witness.json';target.write_bytes(b'old')
            with self.assertRaises(FileExistsError):publish_exclusive(target,b'new')
            self.assertEqual(target.read_bytes(),b'old');self.assertEqual(list(root.iterdir()),[target])
            other=root/'new.json'
            with patch('native_recovery.witness.os.link',side_effect=OSError('injected failure')):
                with self.assertRaises(OSError):publish_exclusive(other,b'complete')
            self.assertFalse(other.exists());self.assertEqual(list(root.iterdir()),[target])
            publish_exclusive(other,b'complete');self.assertEqual(other.read_bytes(),b'complete')

    def test_postpublication_cleanup_reports_success_and_preserves_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'out'; real_unlink=os.unlink
            with patch('native_recovery.witness.os.unlink',side_effect=PermissionError('simulated cleanup')) as cleanup:
                warning=publish_exclusive(target,b'complete')
            self.assertIn('simulated cleanup',warning);self.assertEqual(cleanup.call_count,1)
            self.assertEqual(target.read_bytes(),b'complete')
            stage=next(p for p in Path(directory).iterdir() if p!=target);real_unlink(stage)
            with self.assertRaises(FileExistsError):publish_exclusive(target,b'other')
            self.assertEqual(target.read_bytes(),b'complete')

    def test_primary_and_cleanup_failure_both_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'out';real_unlink=os.unlink
            with patch('native_recovery.witness.os.link',side_effect=RuntimeError('primary')), patch('native_recovery.witness.os.unlink',side_effect=PermissionError('cleanup')) as cleanup:
                with self.assertRaisesRegex(RuntimeError,'primary') as caught:publish_exclusive(target,b'bytes')
            self.assertIn('cleanup',caught.exception.__notes__[0]);self.assertEqual(cleanup.call_count,1)
            self.assertFalse(target.exists());real_unlink(next(Path(directory).iterdir()))
            self.assertIsNone(publish_exclusive(target,b'good'));self.assertEqual(target.read_bytes(),b'good')

    def test_regular_descriptor_admission_refuses_fifo_symlink_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);regular=root/'good';regular.write_bytes(b'good');self.assertEqual(capture_witness(regular),b'good')
            fifo=root/'fifo';os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError,'regular'):capture_witness(fifo)
            link=root/'link';link.symlink_to(regular)
            with self.assertRaises(OSError):capture_witness(link)
            large=root/'large';large.write_bytes(b'x'*(1024*1024+1))
            with self.assertRaisesRegex(ValueError,'regular'):capture_witness(large)

    def test_non_sat_never_produces_witness(self):
        for status in ('unknown','unsat'):
            with self.subTest(status=status),self.assertRaises(ValueError):
                create(self.request,self.code,self.fn.address,self.fn.name,{'verification':{'status':status}},run_operation)
