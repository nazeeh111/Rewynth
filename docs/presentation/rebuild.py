"""Compile only the included generated model C and authored caller in a fresh temp directory.
Never load or execute the original ARM64 fixture. Requires an existing C11 compiler.
"""
from pathlib import Path
import tempfile,subprocess,json,hashlib,os
P=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='rewynth-export-callers-') as td:
 d=Path(td);commands=[]
 for name,entry in [('original','original_transition'),('edited','edited_transition')]:
  cmd=['cc','-std=c11','-Wall','-Wextra','-Wno-unused-parameter','-Werror','-O2','-Drewynth_transition='+entry,'-c',str(P/(name+'.c')),'-o',str(d/(name+'.o'))];subprocess.run(cmd,check=True,capture_output=True);commands.append(cmd)
 cmd=['cc','-std=c11','-Wall','-Wextra','-Werror',str(P/'caller.c'),str(d/'original.o'),str(d/'edited.o'),'-o',str(d/'caller')];subprocess.run(cmd,check=True,capture_output=True);commands.append(cmd)
 run=subprocess.run([str(d/'caller')],check=True,capture_output=True,text=True);result=json.loads(run.stdout)
 expected=json.loads((P/'browser.json').read_text());assert result['next_original']==int(expected['nextOriginal'],0);assert result['next_from_edited']==int(expected['nextEdit'],0);assert result['first_original']==result['first_edited'];assert result['next_original']!=result['next_from_edited'];assert result['memory_original']!=result['memory_edited']
 print(json.dumps({'compiler':subprocess.check_output(['cc','--version'],text=True).splitlines()[0],'scope':'Generated pure logical transition C and authored caller only; original target not executed','result':result,'matchesActualBrowserContinuation':True,'commands':commands,'sourceSHA256':{n:hashlib.sha256((P/n).read_bytes()).hexdigest() for n in ['original.c','edited.c','caller.c']}},indent=2))
