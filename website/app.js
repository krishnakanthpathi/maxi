const examples={
  dictate:{command:'“Dictate: Here’s the idea I don’t want to lose.”',badge:'THOUGHT → TEXT',title:'A thought, without the detour.',description:'Start with “Dictate:” to send transcribed text to your cursor, without an LLM round trip. Keep your attention on the work in front of you.',detail:'Text insertion requires Accessibility permission.',preview:'“Dictate: A little room to focus.”',answer:'A little room to focus.',meta:'DICTATION',result:'Ready to insert ↗'},
  tools:{command:'“Open the app I need for my next task.”',badge:'INTENT → ACTION',title:'A shorter path to the next thing.',description:'Connect an MCP server to make desktop actions available to your model. Ask naturally, see which tools are running, and read the result in the floating HUD.',detail:'Available actions depend on your connected MCP servers.',preview:'“Open my notes app.”',answer:'Your connected tools can take it from here.',meta:'DESKTOP TOOLS',result:'Example action ↗'},
  memory:{command:'“Remember: I prefer short, direct answers.”',badge:'PREFERENCE → MEMORY',title:'Keep the useful bits. Start fresh.',description:'With optional LightMem, explicitly save a preference or look up a fact you’ve stored. New Chat clears recent conversation while leaving deliberately saved facts separate.',detail:'Requires LightMem. This beta does not automatically inject memories.',preview:'“Remember: keep my answers concise.”',answer:'A preference worth keeping, when you choose.',meta:'OPTIONAL LIGHTMEM',result:'Example preference ↗'}
};
let currentExample='dictate', demoRunning=false;
const byId=id=>document.getElementById(id);
function showExample(key){
  currentExample=key;const item=examples[key];
  for(const button of document.querySelectorAll('[data-example]')){const selected=button.dataset.example===key;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;}
  byId('example-panel').setAttribute('aria-labelledby','tab-'+key);
  for(const name of ['command','badge','title','description','detail'])byId('example-'+name).textContent=item[name];
  byId('preview-request').textContent=item.preview;byId('preview-answer').textContent=item.answer;byId('preview-meta').textContent=item.meta;byId('preview-result').textContent=item.result;
}
for(const button of document.querySelectorAll('[data-example]'))button.addEventListener('click',()=>showExample(button.dataset.example));
function keyboardTabs(selector,onSelect){
  const buttons=[...document.querySelectorAll(selector)];
  buttons.forEach((button,index)=>button.addEventListener('keydown',event=>{let next;if(event.key==='ArrowRight')next=(index+1)%buttons.length;else if(event.key==='ArrowLeft')next=(index+buttons.length-1)%buttons.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=buttons.length-1;else return;event.preventDefault();buttons[next].focus();onSelect(buttons[next]);}));
}
keyboardTabs('[data-example]',button=>showExample(button.dataset.example));
byId('try-demo').addEventListener('click',async()=>{
  if(demoRunning)return;demoRunning=true;
  const button=byId('try-demo');button.setAttribute('aria-busy','true');button.classList.add('listening');byId('pill-label').textContent='Listening…';byId('announcer').textContent='Illustrative preview. No microphone is being used.';
  await new Promise(resolve=>setTimeout(resolve,window.matchMedia('(prefers-reduced-motion: reduce)').matches?200:1200));
  const keys=Object.keys(examples);showExample(keys[(keys.indexOf(currentExample)+1)%keys.length]);
  button.classList.remove('listening');byId('pill-label').textContent='Hold right ⌥ to speak';button.removeAttribute('aria-busy');demoRunning=false;
  byId('announcer').textContent='Example changed: '+examples[currentExample].title;
});
const install={
  mac:{comment:'# Backend wheel first. Native app next. Python setup is automatic.',code:'curl -fsSL https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/scripts/install.sh | bash',detail:'Wheel → app → backend health check → ready · macOS 14+'},
  linux:{comment:'# Automated setup: uv, Python 3.12, backend wheel, and daemon service.',code:'curl -fsSL https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/scripts/install.sh | bash',detail:'Wheel → Python via uv → systemd user service → ready · Linux (x86_64 / arm64)'},
  windows:{comment:'# PowerShell · backend support, without a native GUI.',code:'py -m venv "$HOME\\.maxi\\venv"\n& "$HOME\\.maxi\\venv\\Scripts\\python.exe" -m pip install \\\n  "https://github.com/krishnakanthpathi/maxi/releases/download/v0.3.0-beta.1/maxi_ai-0.3.0b1-py3-none-any.whl[voice]"\n& "$HOME\\.maxi\\venv\\Scripts\\maxi.exe" config wizard\n& "$HOME\\.maxi\\venv\\Scripts\\maxi.exe" start',detail:'Python 3.10+ · configure your providers · Ctrl + Space'}
};
// PowerShell uses a backtick for continuation, unlike the Unix shell.
install.windows.code=install.windows.code.replace(/ \\\n/g,' `\n');
let currentPlatform='mac';
function showInstall(platform){currentPlatform=platform;const item=install[platform];for(const button of document.querySelectorAll('[data-platform]')){const selected=button.dataset.platform===platform;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;}byId('install-code').setAttribute('aria-labelledby','install-'+platform);byId('install-code').querySelector('code').textContent=item.code;byId('install-comment').textContent=item.comment;byId('install-detail').textContent=item.detail;}
for(const button of document.querySelectorAll('[data-platform]'))button.addEventListener('click',()=>showInstall(button.dataset.platform));
keyboardTabs('[data-platform]',button=>showInstall(button.dataset.platform));
byId('copy-install').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(install[currentPlatform].code);byId('copy-install').textContent='Copied ✓';byId('announcer').textContent='Installation commands copied.';}catch{const selection=window.getSelection();const range=document.createRange();range.selectNodeContents(byId('install-code'));selection.removeAllRanges();selection.addRange(range);byId('copy-install').textContent='Select + copy';byId('announcer').textContent='Select and copy the highlighted commands.';}setTimeout(()=>{byId('copy-install').textContent='Copy ⧉';},2200);});
showInstall('mac');
