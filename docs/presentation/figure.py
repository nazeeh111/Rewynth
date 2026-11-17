"""Draw only exact values from the actual bounded comparison and native caller.
Arrows show model continuations, not time measurements or native target execution.
"""
from pathlib import Path
import json,html
P=Path(__file__).resolve().parent;e=json.loads((P/'comparison.json').read_text());w=e['result']['verification']['counterexample'];c=json.loads((P/'native-caller.json').read_text())['result'];n=lambda v:int(str(v),0);hx=lambda v:f'0x{n(v):016x}';assert n(w['original_output_u64'])==n(w['candidate_output_u64'])==c['first_original'];assert c['next_original']!=c['next_from_edited'];assert w['original_memory_u64'][1]==w['candidate_memory_u64'][1]
def draw(mobile):
 W,H=(420,1280) if mobile else (1200,860);m=28 if mobile else 44;s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">','<title id="title">Rewynth: the return hides a lost state update</title>','<desc id="desc">The original ARM64 instruction model and edited transition return 0xafeddd80. Their first state word differs. The next call of the original model yields 0x7d367e8e from the original post-state and 0xafeddd80 from the edited post-state. Generated pure C independently reproduces this result.</desc>','<style>text{font-family:Arial,Helvetica,sans-serif;fill:#182039}.muted{fill:#4d5e7b}.mono{font-family:"Courier New",Courier,monospace}.blue{fill:#2458ba}.red{fill:#9c2e43}</style>',f'<rect width="{W}" height="{H}" fill="#f3f5f8"/>']
 def t(x,y,v,size=20,cls='',weight=400):s.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" class="{cls}">{html.escape(v)}</text>')
 t(m,50,'rewynth',29,weight=700)
 if mobile:t(m,108,'The return hides',35,weight=700);t(m,150,'the lost update.',35,weight=700)
 else:t(m,118,'The return hides the lost update.',50,weight=700)
 t(m,192 if mobile else 166,'An actual bounded ARM64 comparison.',18,'muted')
 if mobile:
  t(m,248,'Initial state',17,'muted');t(m,280,hx(w['inputs_u64'][0]),22,'mono');t(m,320,'Same first return in both models',20,'blue',700);t(m,354,hx(w['original_output_u64']),25,'mono')
  for i,(label,mem,ret) in enumerate([('Recovered transition',w['original_memory_u64'][0],c['next_original']),('Lost-store edit',w['candidate_memory_u64'][0],c['next_from_edited'])]):
   y=422+i*310;s.append(f'<path d="M28 {y-25}H392" stroke="#aab8ce"/>');t(m,y,label,25,'red' if i else'blue',700);t(m,y+47,'Post-state memory[0]',18,'muted');t(m,y+83,hx(mem),22,'mono');s.append(f'<path d="M48 {y+103}V{y+151}m-6-7 6 7 6-7" fill="none" stroke="#4d5e7b" stroke-width="2"/>');t(m,y+184,'Next original-model return',18,'muted');t(m,y+220,hx(ret),22,'mono')
  t(m,1067,'memory[1] retained in both:',18,'muted');t(m,1101,hx(w['original_memory_u64'][1]),21,'mono');t(m,1153,'Generated C reproduces the split.',21,'blue',700);t(m,1193,'Pure logical ABI; original target not run.',16,'muted');t(m,1230,'A model/domain result, not a CPU proof.',16,'muted')
 else:
  t(m,220,'Initial memory[0] / state',18,'muted');t(m,255,hx(w['inputs_u64'][0]),24,'mono');t(625,220,'Initial memory[1] / increment',18,'muted');t(625,255,hx(w['inputs_u64'][1]),24,'mono')
  for i,(label,mem,ret) in enumerate([('Recovered transition',w['original_memory_u64'][0],c['next_original']),('Lost-store edit',w['candidate_memory_u64'][0],c['next_from_edited'])]):
   x=m+i*580;s.append(f'<path d="M{x} 300H{x+530}" stroke="#aab8ce"/>');t(x,344,label,30,'red' if i else'blue',700);t(x,394,'Immediate return, equal',19,'muted');t(x,435,hx(w['original_output_u64']),27,'mono');t(x,493,'Post-state memory[0], different',19,'muted');t(x,534,hx(mem),27,'mono');s.append(f'<path d="M{x+20} 558V604m-6-7 6 7 6-7" fill="none" stroke="#4d5e7b" stroke-width="2"/>');t(x,644,'Next call of the original model',19,'muted');t(x,685,hx(ret),27,'mono')
  t(m,755,'memory[1] is retained in both. Generated pure C reproduces both continuations.',21,'blue',700);t(m,802,'Logical uint64 inputs and returned state; original pointer ABI and target execution are outside this check.',18,'muted');t(m,838,'One declared pointer, two words, one fixed synthetic base. Equality remains conditional on the implemented model.',17,'muted')
 s.append('</svg>');return'\n'.join(s)+'\n'
for name,m in [('lost-update',False),('lost-update-mobile',True)]:(P/(name+'.svg')).write_text(draw(m))
