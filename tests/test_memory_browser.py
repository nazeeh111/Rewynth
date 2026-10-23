"""Execute the shipped UI in a small DOM stub, without browser/native targets."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


WEB = Path(__file__).resolve().parents[1] / "src/native_recovery/resources/web"
HARNESS = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const elements = new Map();
class Element {
  constructor(tag='div') { this.tagName=tag; this.children=[]; this.dataset={}; this.events={}; this._value=''; this.textContent=''; this.className=''; this.hidden=false; this.disabled=false; this.checked=false; this.type=''; this.classList={add:(v)=>{this.className += ' '+v;}}; }
  set id(value) { this._id=value; elements.set(value,this); }
  get id() { return this._id; }
  set value(value) { this._value=String(value); }
  get value() { return this._value || (this.tagName==='select' ? this.children[0]?.value ?? '' : ''); }
  get options() { return this.children; }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children=values; }
  setAttribute(name,value) { this[name]=value; }
  addEventListener(name,fn) { (this.events[name] ??= []).push(fn); }
  async fire(name) { for (const fn of this.events[name] || []) await fn({target:this}); }
  dispatchEvent(event) { return this.fire(event.type); }
  querySelectorAll(selector) { const found=[]; const walk=(node)=>{for(const child of node.children || []) {if(child.tagName==='input')found.push(child); walk(child);}}; walk(this); return found; }
  querySelector(selector) { return this.querySelectorAll('input').find(e=>selector==='input[type=checkbox]' ? e.type==='checkbox' : selector==='[data-min]' ? Object.hasOwn(e.dataset,'min') : Object.hasOwn(e.dataset,'max')); }
  scrollIntoView() {}
  click() { return this.fire('click'); }
}
const html=fs.readFileSync(WEB+'/index.html','utf8');
for(const match of html.matchAll(/<([a-z]+)[^>]*\bid="([^"]+)"[^>]*>/g)) { const el=new Element(match[1]); el.id=match[2]; }
const $=id=>{assert.ok(elements.has(id), 'Missing HTML id '+id); return elements.get(id);};
for(const [id,values] of [['arity',[1,2,3,4]],['word-bits',[32,64]],['memory-argument',[0]],['memory-words',[1,2,3]]]) for(const value of values) {const el=new Element('option');el.value=value;$(id).append(el);}
$('arity').value='1'; $('word-bits').value='32'; $('target').value='128'; $('inverse-target').value='128';
const requests=[];
const entered={sha256:'a'.repeat(64),format:'Mach-O',size:16,functions:[{name:'_pcg32_random_r',size:16,supported_size:true},{name:'_kernel_clamp',size:16,supported_size:true}]};
const response=value=>({ok:true,json:async()=>value,arrayBuffer:async()=>new Uint8Array([1,2,3]).buffer});
const context=vm.createContext({console,Blob,URL,Uint8Array,JSON,Number,BigInt,Object,Array,String,Error,Date,Event:class{constructor(type){this.type=type;}},
  document:{getElementById:$,createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})},
  setTimeout:()=>1,clearTimeout:()=>{},btoa:s=>Buffer.from(s,'binary').toString('base64'),
  fetch:async(path,options)=>{requests.push([path,options ? JSON.parse(options.body) : null]);return response(entered);},
  evaluateProgram:()=>0n});
let source=fs.readFileSync(WEB+'/app.js','utf8');
source=source.replace(/^import[^\n]+\n/,'').split("try {\n  token =")[0];
vm.runInContext(source+`\nglobalThis.api={memoryControls,widthLabels,inputFields,settings,workspace,loadWorkspace,validateWorkspace,working,invalidate,proof,trace,render,run,openBytes,seed(){artifact=${JSON.stringify(entered)};artifactData='AQID';artifactName='original';},state(){return {artifact,result,generatedSource,lastEvidence};}};`,context);
const api=context.api;
api.seed(); api.memoryControls(); api.widthLabels(); api.inputFields();
function memory(arity=1,argument=0,words=2) { $('word-bits').value='64';$('arity').value=String(arity);$('memory-enabled').checked=true;api.memoryControls();$('memory-argument').value=String(argument);$('memory-words').value=String(words);api.memoryControls();api.widthLabels();api.inputFields(); }
function saved(version=3) { return {schema:'rewynth.workspace',version,artifact:{name:'saved',sha256:entered.sha256,data:'AQID'},settings:{symbol:'_pcg32_random_r',arity:1,word_bits:64,domain:[null,null],memory:{argument:0,words:2}},expression:'{"return":"x0","memory":["x0","x1"]}',queries:{inputs:['0x853c49e6748fea9b','0xda3e39cb94b95bdb'],target:'128'}}; }
const model={instructions:[],assumptions:{memory:{argument:0,words:2}}};
"""


class MemoryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node is required for shipped UI contract checks")

    def check_js(self, body):
        script = "const WEB=" + json.dumps(str(WEB)) + ";\n" + HARNESS
        result = subprocess.run(
            [self.node, "--input-type=commonjs", "--eval", script + "\n(async()=>{\n" + body + "\n})().catch(error=>{console.error(error);process.exitCode=1;});"],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_logical_mapping_and_joint_evaluation_request(self):
        self.check_js(r"""
memory(3,1,2);
assert.equal($('domains').children.length,4);
assert.equal($('inputs').children[0].textContent,'x0 / x0 scalar');
assert.equal($('inputs').children[2].textContent,'x1 / x2 scalar');
assert.match($('inputs').children[4].textContent,/x2 \/ memory\[0\]/);
for(let i=0;i<4;i++)$('arg-'+i).value=['0x20000000000001','7','9','11'][i];
context.fetch=async(path,options)=>{const body=options ? JSON.parse(options.body):null;requests.push([path,body]);return response(path==='/api/jobs'?{job:'one'}:{state:'done',result:{kind:'evaluate',model,witness:{inputs_u64:['9007199254740993','7','9','11'],output_u64:'5',memory_u64:['13','11'],trace:[]}}});};
await api.run('evaluate');
const sent=requests.find(r=>r[0]==='/api/jobs')[1];
assert.deepEqual(sent.memory,{argument:1,words:2}); assert.equal(sent.arity,3);assert.equal(sent.domain.length,4);
assert.deepEqual(sent.inputs,['9007199254740993','7','9','11']);
assert.match($('witness').textContent,/Post-state: memory\[0\] = 0x000000000000000d/);
api.working(false);assert.equal($('inverse').disabled,true);assert.equal($('derive_inverse').disabled,true);
const count=requests.length;await assert.rejects(api.run('inverse'),/unavailable/);await assert.rejects(api.run('derive_inverse'),/unavailable/);assert.equal(requests.length,count);
""")

    def test_memory_only_counterexample_and_same_pc_pair_trace(self):
        self.check_js(r"""
memory();
api.proof({status:'sat',counterexample:{inputs_u64:['1','3'],original_output_u64:'7',candidate_output_u64:'7',original_memory_u64:['8','3'],candidate_memory_u64:['1','3'],differences:['memory[0]'],trace:[{address:'0x1000',instruction:'ldp x1, x2, [x0]',destination:'x1',kind:'memory_read',value_u64:'1'},{address:'0x1000',instruction:'ldp x1, x2, [x0]',destination:'x2',kind:'memory_read',value_u64:'3'},{address:'0x1004',instruction:'str x1, [x0]',destination:'memory[0:8]',kind:'memory_write',value_u64:'8'}]}});
assert.match($('proof').textContent,/Changed: memory\[0\]/);assert.match($('proof').textContent,/Original return 0x0000000000000007; edit return 0x0000000000000007/);
assert.match($('proof').textContent,/Original post-state: memory\[0\] = 0x0000000000000008/);
assert.match($('proof').textContent,/Edit post-state: memory\[0\] = 0x0000000000000001/);
assert.equal($('trace').children.length,3);assert.equal($('trace').children[2].children[2].textContent,'memory[0:8]');
api.proof({status:'unknown',reason:'timeout'});assert.equal($('trace-panel').hidden,true);assert.match($('proof').textContent,/No equivalence conclusion/);
api.proof({status:'unsat'});assert.match($('proof').textContent,/return and every declared post-state word/);
""")

    def test_workspace_v3_exact_declaration_queries_and_import_unverified(self):
        self.check_js(r"""
memory();$('symbol').value='_pcg32_random_r';$('expression').value=saved().expression;
$('arg-0').value='  0x853c49e6748fea9b  ';$('arg-1').value='0xda3e39cb94b95bdb';
const packet=JSON.parse(JSON.stringify(api.workspace()));
assert.equal(packet.version,3);assert.deepEqual(packet.settings.memory,{argument:0,words:2});assert.equal(packet.queries.inputs[0],'  0x853c49e6748fea9b  ');
await api.loadWorkspace(packet);
assert.equal($('arg-0').value,packet.queries.inputs[0]);assert.equal($('arg-1').value,packet.queries.inputs[1]);assert.equal($('expression').value,packet.expression);
assert.match($('proof').textContent,/saved evidence is not a fresh proof/);assert.equal(api.state().lastEvidence,null);assert.equal(api.state().generatedSource,null);assert.equal($('inverse').disabled,true);
""")

    def test_invalid_workspace_settings_do_not_replace_artifact_or_issue_request(self):
        self.check_js(r"""
const mutate=[v=>v.settings.word_bits=32,v=>v.settings.memory.argument=1,v=>v.settings.memory.argument=true,v=>v.settings.memory.words=4,v=>v.settings.memory.words=1.5,v=>v.settings.memory.extra=1,v=>v.settings.memory=null,v=>v.settings.arity='1',v=>{v.settings.arity=4;v.settings.memory.words=2;},v=>v.settings.domain=[null],v=>v.settings.domain[0]={min:'-1',max:'1',signed:false},v=>v.settings.domain[0]={min:'0',max:'18446744073709551616',signed:false},v=>v.queries.inputs=['1'],v=>v.queries.target=1,v=>v.queries=null,v=>v.version=2];
for(const change of mutate){const packet=saved();change(packet);await assert.rejects(api.loadWorkspace(packet));assert.equal(api.state().artifact.sha256,entered.sha256);}
assert.equal(requests.length,0);
""")

    def test_v1_v2_register_workspaces_remain_readable(self):
        self.check_js(r"""
for(const version of [1,2]){const packet=saved(version);delete packet.settings.memory;packet.settings.word_bits=version===1?32:64;packet.settings.domain=[null];packet.expression='x0+1';packet.queries.inputs=['7'];await api.loadWorkspace(packet);assert.equal($('memory-enabled').checked,false);assert.equal($('domains').children.length,1);assert.equal($('expression').value,'x0+1');assert.equal($('arg-0').value,'7');api.working(false);assert.equal($('inverse').disabled,false);}
""")

    def test_memory_changes_invalidate_and_32_bit_switch_clears_declaration(self):
        self.check_js(r"""
memory();api.render({kind:'recover',model,reconstruction:{grammar:'joint',verification:{status:'unsat'}},expression:saved().expression,source:'struct transition {}'});
assert.ok(api.state().generatedSource);$('memory-words').value='3';await $('memory-words').fire('change');assert.equal($('domains').children.length,3);assert.equal(api.state().generatedSource,null);assert.equal(api.state().lastEvidence,null);assert.equal($('reset-expression').disabled,true);
$('word-bits').value='32';await $('word-bits').fire('change');assert.equal($('memory-enabled').checked,false);assert.equal($('memory-enabled').disabled,true);assert.equal(api.settings().memory,undefined);assert.equal($('domains').children.length,1);
""")

    def test_example_memory_defaults_and_reset_to_old_register_example(self):
        self.check_js(r"""
await $('example-memory').fire('click');
assert.equal(requests[0][0],'/example-memory');assert.equal($('word-bits').value,'64');assert.equal($('arity').value,'1');assert.equal($('symbol').value,'_pcg32_random_r');assert.equal(api.settings().memory.words,2);assert.equal($('arg-0').value,'0x853c49e6748fea9b');assert.equal($('arg-1').value,'0xda3e39cb94b95bdb');
await $('example').fire('click');assert.equal($('word-bits').value,'32');assert.equal($('memory-enabled').checked,false);assert.equal($('symbol').value,'_kernel_clamp');assert.equal(api.settings().memory,undefined);
""")

    def test_transition_text_sent_unchanged_and_restore_resets_proof(self):
        self.check_js(r"""
memory();const expression='{"return":"x0", "memory":["x0+1", "x1"]}';
api.render({kind:'recover',model,reconstruction:{grammar:'joint',verification:{status:'unsat'}},expression,source:'struct transition recovered;'});
const edit='  {"return":"x0",\n "memory":["x0", "x1"]}  ';$('expression').value=edit;await $('expression').fire('input');
context.fetch=async(path,options)=>{const body=options ? JSON.parse(options.body):null;requests.push([path,body]);return response(path==='/api/jobs'?{job:'one'}:{state:'done',result:{kind:'verify',model,verification:{status:'unsat'},source:'struct transition candidate;'}});};
await api.run('verify');assert.equal(requests[0][1].expression,edit);assert.equal($('c-source').textContent,'struct transition candidate;');
await $('reset-expression').fire('click');assert.equal($('expression').value,expression);assert.equal(api.state().generatedSource,null);assert.match($('proof').textContent,/previous comparison does not apply/);
""")

    def test_register_only_request_and_stale_memory_job(self):
        self.check_js(r"""
$('arg-0').value='7';context.fetch=async(path,options)=>{requests.push([path,options ? JSON.parse(options.body):null]);return response(path==='/api/jobs'?{job:'register'}:{state:'done',result:{kind:'evaluate',model,witness:{inputs_u32:[7],output_u32:8,trace:[]}}});};
await api.run('evaluate');assert.deepEqual(requests[0][1].inputs,[7]);assert.equal(requests[0][1].memory,undefined);assert.match($('witness').textContent,/w0 = 0x00000008/);
memory();let complete;context.fetch=async(path,options)=>{requests.push([path,options ? JSON.parse(options.body):null]);if(path==='/api/jobs')return await new Promise(resolve=>{complete=resolve;});return response({});};
const pending=api.run('recover');$('memory-words').value='3';await $('memory-words').fire('change');complete(response({job:'stale'}));await pending;
assert.equal(api.state().result,null);assert.ok(requests.some(r=>r[0]==='/api/cancel/stale'));assert.equal($('domains').children.length,3);assert.equal($('inverse').disabled,true);
""")


    def test_next_call_uses_post_state_keeps_scalar_order_and_clears_on_edit(self):
        self.check_js(r"""
memory(3,1,2);
const witness={inputs_u64:['9007199254740993','7','9','11'],original_output_u64:'5',candidate_output_u64:'5',original_memory_u64:['13','11'],candidate_memory_u64:['9','11'],differences:['memory[0]'],trace:[]};
api.proof({status:'sat',counterexample:witness});
assert.equal($('state-comparison').hidden,false);
assert.equal($('state-words').children[0].children[1].textContent,'0x0000000000000009');
context.fetch=async(path,options)=>{const body=options ? JSON.parse(options.body):null;requests.push([path,body]);return response(path==='/api/jobs'?{job:'next'}:{state:'done',result:{kind:'evaluate',model,witness:{inputs_u64:body?.inputs??['9007199254740993','7','13','11'],output_u64:'9007199254740995',memory_u64:['17','11'],trace:[]}}});};
await $('continue-original').fire('click');
assert.deepEqual(requests.find(r=>r[0]==='/api/jobs')[1].inputs,['9007199254740993','7','13','11']);
assert.equal($('next-original').textContent,'0x0020000000000003');
requests.length=0;await $('continue-edit').fire('click');
assert.deepEqual(requests.find(r=>r[0]==='/api/jobs')[1].inputs,['9007199254740993','7','9','11']);
$('expression').value='new edit';await $('expression').fire('input');
assert.equal($('state-comparison').hidden,true);assert.equal($('trace-panel').hidden,true);
""")

    def test_failed_or_cancelled_next_trace_never_claims_a_return(self):
        self.check_js(r"""
memory();const witness={inputs_u64:['1','3'],original_output_u64:'7',candidate_output_u64:'7',original_memory_u64:['8','3'],candidate_memory_u64:['1','3'],differences:['memory[0]'],trace:[]};
api.proof({status:'sat',counterexample:witness});
context.fetch=async(path,options)=>response(path==='/api/jobs'?{job:'refused'}:{state:'failed',error:'Input outside declared domain'});
await $('continue-original').fire('click');assert.match($('next-original').textContent,/Not established: Input outside declared domain/);
let complete;context.fetch=async(path,options)=>path==='/api/jobs'?await new Promise(resolve=>{complete=resolve;}):response({});
const pending=$('continue-edit').fire('click');await $('cancel').fire('click');complete(response({job:'cancelled'}));await pending;
assert.match($('next-edit').textContent,/Cancelled/);
""")

    def test_cancelled_continuation_cannot_replace_newer_return(self):
        self.check_js(r"""
memory();api.proof({status:'sat',counterexample:{inputs_u64:['1','3'],original_output_u64:'7',candidate_output_u64:'7',original_memory_u64:['8','3'],candidate_memory_u64:['1','3'],differences:['memory[0]'],trace:[]}});
let finishOld;context.fetch=async(path)=>path==='/api/jobs'?await new Promise(resolve=>{finishOld=resolve;}):response({});
const old=$('continue-original').fire('click');await $('cancel').fire('click');
context.fetch=async(path)=>response(path==='/api/jobs'?{job:'new'}:path.startsWith('/api/cancel/')?{}:{state:'done',result:{kind:'evaluate',model,witness:{inputs_u64:['8','3'],output_u64:'42',memory_u64:['9','3'],trace:[]}}});
await $('continue-original').fire('click');
assert.equal($('next-original').textContent,'0x000000000000002a');
const notice=$('notice').textContent;
finishOld(response({job:'old'}));await old;
assert.equal($('next-original').textContent,'0x000000000000002a');
assert.equal($('notice').textContent,notice);
""")

if __name__ == "__main__":
    unittest.main()
