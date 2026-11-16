"""Bounded artifact file admission; no target code is executed."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from native_recovery.artifacts import Artifact, ArtifactError, MAX_ARTIFACT, capture_artifact

FIXTURE=Path(__file__).parents[1]/'src/native_recovery/resources/examples/pcg-basic.o'

class ArtifactAdmissionTests(unittest.TestCase):
    def test_regular_and_symlink(self):
        data=FIXTURE.read_bytes(); self.assertEqual(capture_artifact(FIXTURE),data)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'linked';path.symlink_to(FIXTURE)
            self.assertEqual(capture_artifact(path),data)
            self.assertEqual(Artifact(capture_artifact(path)).digest,Artifact(data).digest)

    def test_fifo_directory_oversize_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fifo=root/'fifo';os.mkfifo(fifo)
            with self.assertRaisesRegex(ArtifactError,'regular'):capture_artifact(fifo)
            with self.assertRaisesRegex(ArtifactError,'regular'):capture_artifact(root)
            big=root/'big'
            with big.open('wb') as f:f.truncate(MAX_ARTIFACT+1)
            with self.assertRaisesRegex(ArtifactError,'32 MiB'):capture_artifact(big)

    def test_growth_after_stat_is_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'growing';path.write_bytes(b'x'*32); real_fstat=os.fstat
            def grow(fd):
                info=real_fstat(fd)
                with path.open('ab') as f:f.truncate(MAX_ARTIFACT+1)
                return info
            with patch('native_recovery.artifacts.os.fstat',side_effect=grow):
                with self.assertRaisesRegex(ArtifactError,'32 MiB'):capture_artifact(path)

    def test_path_replacement_after_open_uses_captured_descriptor(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'sample';original=FIXTURE.read_bytes();path.write_bytes(original)
            real_fstat=os.fstat
            def replace(fd):
                info=real_fstat(fd);path.rename(root/'moved');path.write_bytes(b'foreign data')
                return info
            with patch('native_recovery.artifacts.os.fstat',side_effect=replace):
                captured=capture_artifact(path)
            self.assertEqual(captured,original);self.assertEqual(path.read_bytes(),b'foreign data')
            self.assertEqual(Artifact(captured).digest,Artifact(original).digest)
