var e=`researchAssistantArchitectureWorkbenchV2`;globalThis[e]||(globalThis[e]=!0,document.readyState===`loading`?document.addEventListener(`DOMContentLoaded`,t,{once:!0}):t());function t(){let e=`__root__`,t={bootstrap:null,files:[],document:l(),path:null,revision:null,selectedNode:null,activeTemplate:e},n=(e,t=document)=>t.querySelector(e),r=(e,t,n)=>{let r=document.createElement(e);return t&&(r.className=t),n!==void 0&&(r.textContent=n),r},i=e=>structuredClone(e),a=e=>JSON.stringify(e),o=(e,t=`JSON value`)=>{try{return JSON.parse(e)}catch{throw Error(`Invalid ${t}: ${e}`)}},s=async(e,t={})=>{let n=await fetch(e,{...t,headers:{...t.body?{"Content-Type":`application/json`}:{},...t.headers}}),r=await n.json().catch(()=>({detail:n.statusText}));if(!n.ok)throw Error(r.detail||`Request failed (${n.status})`);return r};function c(e=[`input`]){return{input_names:[...e],nodes:[],outputs:{output:e[0]}}}function l(){return{format:`research-assistant/torch-architecture`,version:2,name:`model`,description:``,graph:{variables:{},variable_specs:{},...c(),subgraphs:{}}}}function u(e){if(!e||typeof e!=`object`)throw Error(`Architecture must be an object`);if(e.format&&e.format!==`research-assistant/torch-architecture`)throw Error(`Unsupported architecture format`);let t=e.graph||e,n=Array.isArray(t.outputs)?Object.fromEntries(t.outputs.map((e,n)=>[t.outputs.length===1?`output`:`output_${n}`,e])):t.outputs||{output:t.input_names?.[0]||`input`},r=Object.fromEntries(Object.entries(t.subgraphs||{}).map(([e,t])=>[e,{input_names:t.input_names||[`input`],nodes:(t.nodes||[]).map(d),outputs:Array.isArray(t.outputs)?Object.fromEntries(t.outputs.map((e,n)=>[t.outputs.length===1?`output`:`output_${n}`,e])):t.outputs||{output:t.input_names?.[0]||`input`}}]));return{format:`research-assistant/torch-architecture`,version:2,name:e.name||`model`,description:e.description||``,graph:{variables:t.variables||{},variable_specs:t.variable_specs||{},input_names:t.input_names||[`input`],nodes:(t.nodes||[]).map(d),outputs:n,subgraphs:r}}}function d(e){let t=e.kind||`module`,n=e.output_ports||[`output`];return{id:e.id,kind:t,type:e.type??null,target:e.target??null,template:e.template??null,inputs:i(e.inputs||[`input`]),params:i(e.params||{}),output_ports:[...n],call_style:e.call_style||`auto`,count:e.count??null,weights:e.weights||`independent`,index_name:e.index_name||`index`,carry:i(e.carry||{}),selector:e.selector??null,branches:i(e.branches||{}),default_branch:e.default_branch??null,label:e.label??null,position:e.position||{x:260,y:70}}}let f=r(`style`);f.textContent=`
    .ra-models-v2{width:min(1580px,98vw);height:min(940px,96vh);padding:0;overflow:hidden}
    .ra-models-layout{height:100%;display:grid;grid-template-columns:240px minmax(0,1fr)}
    .ra-models-sidebar{padding:12px;overflow:auto;background:#121923;border-right:1px solid #303846}
    .ra-models-main{min-width:0;display:grid;grid-template-rows:auto auto auto minmax(0,1fr) auto}
    .ra-models-heading,.ra-models-meta,.ra-template-bar,.ra-models-footer{padding:10px 14px;border-bottom:1px solid #303846}
    .ra-models-heading{display:flex;align-items:center;justify-content:space-between}
    .ra-models-meta{display:grid;grid-template-columns:1.2fr 1fr 2fr auto;gap:8px;align-items:end}
    .ra-template-bar{display:grid;grid-template-columns:220px auto auto 1fr 1.4fr;gap:8px;align-items:end}
    .ra-variable-panel{max-height:210px;overflow:auto;padding:8px 14px;border-bottom:1px solid #303846}
    .ra-variable-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}
    .ra-variable-row{display:grid;grid-template-columns:135px 100px 180px 1fr 210px auto;gap:6px;align-items:center;margin:5px 0}
    .ra-variable-row input,.ra-variable-row select{min-width:0}
    .ra-variable-meta{display:grid;grid-template-columns:1fr 1fr;gap:4px}
    .ra-variable-meta .wide{grid-column:1/-1}
    .ra-variable-path{font-size:10px;opacity:.65;overflow:hidden;text-overflow:ellipsis}
    .ra-models-work{min-height:0;display:grid;grid-template-columns:235px minmax(0,1fr) 355px}
    .ra-palette,.ra-inspector{overflow:auto;padding:10px;background:#121923}
    .ra-palette{border-right:1px solid #303846}.ra-inspector{border-left:1px solid #303846}
    .ra-palette-group{margin:10px 0 5px;font-size:11px;letter-spacing:.08em;opacity:.65;text-transform:uppercase}
    .ra-palette-button{width:100%;text-align:left;margin:3px 0;padding:7px;border:1px solid #303846;border-radius:6px;background:transparent;color:inherit}
    .ra-palette-button small{display:block;opacity:.65;margin-top:2px}
    .ra-canvas-scroll{overflow:auto;background-image:radial-gradient(#42506655 1px,transparent 1px);background-size:20px 20px}
    .ra-canvas{position:relative;width:1900px;height:1250px}
    .ra-edges{position:absolute;inset:0;width:1900px;height:1250px;pointer-events:none}
    .ra-edge{fill:none;stroke:#6da0ff;stroke-width:2;opacity:.7}
    .ra-node-v2{position:absolute;width:195px;border:1px solid #516078;border-radius:8px;background:#18212c;box-shadow:0 8px 18px #0006}
    .ra-node-v2.selected{border-color:#6da0ff}.ra-node-v2.output{border-color:#52bc84}.ra-node-v2.input{background:#173027}
    .ra-node-v2 h4{margin:0;padding:8px 10px 2px;cursor:grab}.ra-node-v2 small{display:block;padding:0 10px 4px;opacity:.65;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .ra-node-ports{padding:0 10px 8px;font-size:10px;opacity:.7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .ra-inspector-grid{display:grid;gap:9px}.ra-inspector-title{font-size:11px;text-transform:uppercase;letter-spacing:.08em;opacity:.65;margin-top:8px}
    .ra-input-row{display:grid;grid-template-columns:105px 1fr auto;gap:5px;align-items:center}
    .ra-binding{display:grid;grid-template-columns:minmax(0,1fr) 92px;gap:5px;align-items:end}
    .ra-binding textarea{min-height:55px;resize:vertical}
    .ra-output-row{display:grid;grid-template-columns:115px 1fr auto;gap:5px;align-items:center}
    .ra-json-editor{min-height:82px;font-family:monospace;resize:vertical}
    .ra-models-footer{border-top:1px solid #303846;border-bottom:0;display:flex;align-items:center;justify-content:space-between}
    .ra-models-error{color:#ff8585;max-width:760px;white-space:pre-wrap}.ra-models-valid{color:#72d69d}
    .ra-config-architecture{display:grid;gap:8px;border:1px solid #303846;border-radius:7px;padding:10px}
    .ra-config-variable{display:grid;grid-template-columns:145px 180px 1fr;gap:6px;align-items:center}
    .ra-config-variable.disabled{opacity:.48}.ra-config-variable code{font-size:10px;opacity:.65}
    .ra-template-list button,.ra-architecture-list button{width:100%;text-align:left;padding:7px;margin:2px 0;border:1px solid transparent;background:transparent;color:inherit}
    .ra-template-list button.active,.ra-architecture-list button.active,.ra-template-list button:hover,.ra-architecture-list button:hover{border-color:#6da0ff}
  `,document.head.append(f);let p=r(`button`,`button ghost`,`Models`);p.type=`button`,p.id=`architectures-button`;let m=n(`#experiments-button`);m?.parentNode?.insertBefore(p,m);let h=r(`dialog`,`ra-models-v2`);h.innerHTML=`
    <div class="ra-models-layout">
      <aside class="ra-models-sidebar">
        <div class="section-heading"><h3>Architectures</h3><button id="ra-new-architecture" class="button compact ghost">New</button></div>
        <input id="ra-architecture-filter" placeholder="Filter files…">
        <div id="ra-architecture-list" class="ra-architecture-list"></div>
        <div class="section-heading"><h3>Subgraphs</h3><button id="ra-new-subgraph-side" class="button compact ghost">New</button></div>
        <div id="ra-template-list" class="ra-template-list"></div>
      </aside>
      <section class="ra-models-main">
        <div class="ra-models-heading"><div><span class="eyebrow">TYPED PYTORCH ARCHITECTURE LANGUAGE</span><h2>Models</h2></div><button id="ra-close-models" class="icon-button">×</button></div>
        <div class="ra-models-meta">
          <label class="field"><span>File</span><input id="ra-architecture-path" value="architectures/model.json"></label>
          <label class="field"><span>Name</span><input id="ra-architecture-name" value="model"></label>
          <label class="field"><span>Description</span><input id="ra-architecture-description"></label>
          <button id="ra-add-variable" class="button ghost">Add variable</button>
        </div>
        <div id="ra-variable-panel" class="ra-variable-panel"></div>
        <div class="ra-template-bar">
          <label class="field"><span>Editing</span><select id="ra-active-template"></select></label>
          <button id="ra-new-subgraph" class="button compact ghost">New subgraph</button>
          <button id="ra-delete-subgraph" class="button compact ghost danger">Delete</button>
          <label class="field"><span>Input ports</span><input id="ra-template-inputs"></label>
          <label class="field"><span>Outputs (JSON mapping)</span><input id="ra-template-outputs"></label>
        </div>
        <div class="ra-models-work">
          <aside class="ra-palette"><input id="ra-palette-filter" placeholder="Filter modules…"><div id="ra-palette-list"></div></aside>
          <div class="ra-canvas-scroll"><div class="ra-canvas"><svg id="ra-edges" class="ra-edges"></svg><div id="ra-nodes"></div></div></div>
          <aside class="ra-inspector"><h3>Inspector</h3><div id="ra-inspector-content" class="ra-inspector-grid">Select a node.</div></aside>
        </div>
        <div class="ra-models-footer"><div><span id="ra-model-status">Not validated</span><div id="ra-model-error" class="ra-models-error"></div></div><div><button id="ra-validate-model" class="button ghost">Validate</button> <button id="ra-save-model" class="button primary">Save</button></div></div>
      </section>
    </div>`,document.body.append(h);let g={architectureList:n(`#ra-architecture-list`,h),architectureFilter:n(`#ra-architecture-filter`,h),templateList:n(`#ra-template-list`,h),path:n(`#ra-architecture-path`,h),name:n(`#ra-architecture-name`,h),description:n(`#ra-architecture-description`,h),variablePanel:n(`#ra-variable-panel`,h),activeTemplate:n(`#ra-active-template`,h),templateInputs:n(`#ra-template-inputs`,h),templateOutputs:n(`#ra-template-outputs`,h),paletteFilter:n(`#ra-palette-filter`,h),paletteList:n(`#ra-palette-list`,h),nodes:n(`#ra-nodes`,h),edges:n(`#ra-edges`,h),inspector:n(`#ra-inspector-content`,h),status:n(`#ra-model-status`,h),error:n(`#ra-model-error`,h)},_=()=>t.document.graph,v=()=>t.bootstrap?.components.filter(e=>e.catalog===`graph-node`)||[],ee=e=>v().find(t=>t.name===e),y=()=>t.activeTemplate===e?_():_().subgraphs[t.activeTemplate];function b(){return Object.keys(_().subgraphs).sort()}function x(e){g.error.textContent=e?.message||String(e),g.status.classList.remove(`ra-models-valid`)}function S(){g.error.textContent=``}function te(){g.path.value=t.path||`architectures/${t.document.name||`model`}.json`,g.name.value=t.document.name,g.description.value=t.document.description}function ne(){t.document.name=g.name.value.trim()||`model`,t.document.description=g.description.value.trim()}function C(){let e=g.architectureFilter.value.trim().toLowerCase();g.architectureList.replaceChildren();for(let n of t.files.filter(t=>t.path.toLowerCase().includes(e))){let e=r(`button`,n.path===t.path?`active`:``,n.path);e.onclick=()=>Ee(n.path).catch(x),g.architectureList.append(e)}g.architectureList.children.length||(g.architectureList.textContent=`No saved architectures.`)}function w(){let i=t.activeTemplate;g.activeTemplate.replaceChildren();let a=r(`option`,null,`Root model`);a.value=e,g.activeTemplate.append(a);for(let e of b()){let t=r(`option`,null,e);t.value=e,g.activeTemplate.append(t)}g.activeTemplate.value=i in _().subgraphs||i===e?i:e,t.activeTemplate=g.activeTemplate.value,g.templateList.replaceChildren();let o=r(`button`,t.activeTemplate===e?`active`:``,`Root model`);o.onclick=()=>T(e),g.templateList.append(o);for(let e of b()){let n=r(`button`,t.activeTemplate===e?`active`:``,e);n.onclick=()=>T(e),g.templateList.append(n)}let s=y();g.templateInputs.value=s.input_names.join(`, `),g.templateOutputs.value=JSON.stringify(s.outputs),n(`#ra-delete-subgraph`,h).disabled=t.activeTemplate===e}function T(e){t.activeTemplate=e,t.selectedNode=null,w(),F()}function re(){let e=window.prompt(`Subgraph name`,`block_${b().length+1}`);if(!e)return;let t=e.trim();if(!/^[A-Za-z][A-Za-z0-9_]*$/.test(t))throw Error(`Invalid subgraph name`);if(_().subgraphs[t])throw Error(`Subgraph ${t} already exists`);_().subgraphs[t]=c(),T(t),k()}function ie(){if(t.activeTemplate===e)return;let n=t.activeTemplate,r=E().filter(e=>e.template===n||Object.values(e.branches||{}).includes(n)||e.default_branch===n);if(r.length)throw Error(`Subgraph ${n} is used by: ${r.map(e=>e.id).join(`, `)}`);window.confirm(`Delete subgraph ${n}?`)&&(delete _().subgraphs[n],T(e))}function E(){return[_().nodes,...Object.values(_().subgraphs).map(e=>e.nodes)].flat()}function ae(e){return e===`bool`?!1:e===`int`?1:e===`float`?0:e===`string`?``:e===`enum`?`option`:e===`shape`?[1]:null}function oe(){let e=1,t=`width`;for(;Object.hasOwn(_().variables,t);)t=`variable_${e++}`;_().variables[t]=64,_().variable_specs[t]={type:`int`,description:``,min:1},D(),W()}function se(e,t){if(!/^[A-Za-z][A-Za-z0-9_]*$/.test(t))throw Error(`Invalid variable name`);if(t!==e&&Object.hasOwn(_().variables,t))throw Error(`Variable ${t} already exists`);if(t===e)return;_().variables[t]=_().variables[e],delete _().variables[e],_().variable_specs[t]=_().variable_specs[e]||{type:`json`},delete _().variable_specs[e];let n=e.replace(/[.*+?^${}()|[\]\\]/g,`\\$&`),r=RegExp(`\\b${n}\\b`,`g`),i=n=>Array.isArray(n)?n.map(i):n&&typeof n==`object`?Object.keys(n).length===1&&n.$var===e?{$var:t}:Object.keys(n).length===1&&typeof n.$expr==`string`?{$expr:n.$expr.replace(r,t)}:Object.fromEntries(Object.entries(n).map(([e,t])=>[e,i(t)])):n;for(let e of E())e.params=i(e.params),e.count=i(e.count),e.selector=i(e.selector);for(let e of Object.values(_().variable_specs))e.enabled_if&&=e.enabled_if.replace(r,t)}function ce(e,t){let n=_().variables[e];if(t.type===`bool`){let t=r(`input`);return t.type=`checkbox`,t.checked=!!n,t.onchange=()=>_().variables[e]=t.checked,t}if(t.type===`enum`){let i=r(`select`);for(let e of t.choices||[]){let t=r(`option`,null,String(e));t.value=JSON.stringify(e),i.append(t)}return i.value=JSON.stringify(n),i.onchange=()=>_().variables[e]=JSON.parse(i.value),i}let i=r(`input`);return t.type===`int`||t.type===`float`?(i.type=`number`,i.step=t.type===`int`?`1`:`any`,t.min!==void 0&&(i.min=String(t.min)),t.max!==void 0&&(i.max=String(t.max)),i.value=String(n),i.onchange=()=>{let n=Number(i.value);if(!Number.isFinite(n)||t.type===`int`&&!Number.isInteger(n))throw Error(`Invalid ${t.type} value for ${e}`);_().variables[e]=n}):t.type===`string`?(i.value=n??``,i.onchange=()=>_().variables[e]=i.value):(i.value=a(n),i.onchange=()=>_().variables[e]=o(i.value)),i}function D(){g.variablePanel.replaceChildren();let e=r(`div`,`ra-variable-head`);e.append(r(`strong`,null,`Architecture variables`),r(`span`,null,`bool · enum · numeric · shape · JSON; matrix overrides target variables.<name>`)),g.variablePanel.append(e);for(let e of Object.keys(_().variables).sort()){let t=_().variable_specs[e]||{type:O(_().variables[e])};_().variable_specs[e]=t;let n=r(`div`,`ra-variable-row`),i=r(`input`);i.value=e,i.onchange=()=>{se(e,i.value.trim()),D(),W()};let a=r(`select`);for(let e of[`int`,`float`,`bool`,`string`,`enum`,`shape`,`json`]){let t=r(`option`,null,e);t.value=e,a.append(t)}a.value=t.type||`json`,a.onchange=()=>{t.type=a.value,t.type===`enum`?(t.choices=t.choices?.length?t.choices:[`option`],_().variables[e]=t.choices[0]):(delete t.choices,_().variables[e]=ae(t.type)),D(),W()};let s=r(`div`);s.append(ce(e,t));let c=r(`div`,`ra-variable-meta`),l=r(`input`);if(l.placeholder=`description`,l.value=t.description||``,l.onchange=()=>t.description=l.value,l.className=`wide`,c.append(l),t.type===`enum`){let n=r(`input`);n.placeholder=`choices JSON, e.g. ["a","b"]`,n.value=JSON.stringify(t.choices||[]),n.className=`wide`,n.onchange=()=>{let r=o(n.value,`enum choices`);if(!Array.isArray(r)||!r.length)throw Error(`Enum choices must be non-empty`);t.choices=r,r.some(t=>JSON.stringify(t)===JSON.stringify(_().variables[e]))||(_().variables[e]=r[0]),D()},c.append(n)}if(t.type===`int`||t.type===`float`){let e=r(`input`);e.type=`number`,e.placeholder=`min`,e.value=t.min??``,e.onchange=()=>{e.value===``?delete t.min:t.min=Number(e.value)};let n=r(`input`);n.type=`number`,n.placeholder=`max`,n.value=t.max??``,n.onchange=()=>{n.value===``?delete t.max:t.max=Number(n.value)},c.append(e,n)}let u=r(`input`);u.placeholder=`enabled_if, e.g. backend == "kuramoto"`,u.value=t.enabled_if||``,u.className=`wide`,u.onchange=()=>{u.value.trim()?t.enabled_if=u.value.trim():delete t.enabled_if},c.append(u);let d=r(`code`,`ra-variable-path`,`components.model.params.variables.${e}`),f=r(`button`,`icon-button`,`×`);f.type=`button`,f.onclick=()=>{delete _().variables[e],delete _().variable_specs[e],D(),W()},n.append(i,a,s,c,d,f),g.variablePanel.append(n)}Object.keys(_().variables).length||g.variablePanel.append(r(`div`,`architecture-empty`,`No variables. Add typed flags, categories or dimensions.`))}function O(e){return typeof e==`boolean`?`bool`:Number.isInteger(e)?`int`:typeof e==`number`?`float`:typeof e==`string`?`string`:Array.isArray(e)&&e.length&&e.every(e=>Number.isInteger(e)&&e>0)?`shape`:`json`}function k(){let e=g.paletteFilter.value.trim().toLowerCase();g.paletteList.replaceChildren();let t=[[`python`,`Python module`,`Import any workspace nn.Module class.`],[`composite`,`Composite`,`Invoke a reusable named subgraph.`],[`repeat`,`Repeat`,`Repeat a subgraph with shared or independent weights.`],[`switch`,`Switch`,`Select a subgraph using bool or enum variables.`]];g.paletteList.append(r(`div`,`ra-palette-group`,`Architecture controls`));for(let[n,i,a]of t){if(!(i+a).toLowerCase().includes(e))continue;let t=r(`button`,`ra-palette-button`);t.append(r(`strong`,null,i),r(`small`,null,a)),t.onclick=()=>ue(n),g.paletteList.append(t)}let n=new Map,i=v().filter(t=>(t.name+` `+t.description).toLowerCase().includes(e)).sort((e,t)=>e.name.localeCompare(t.name));for(let e of i){let t=e.metadata?.category||`Modules`;n.has(t)||n.set(t,[]),n.get(t).push(e)}for(let[e,t]of[...n].sort(([e],[t])=>e.localeCompare(t))){g.paletteList.append(r(`div`,`ra-palette-group`,e));for(let e of t){let t=r(`button`,`ra-palette-button`);t.append(r(`strong`,null,e.name.split(`/`).at(-1)),r(`small`,null,e.description)),t.onclick=()=>le(e),g.paletteList.append(t)}}}function A(e){let t=e.replace(/\W/g,`_`).replace(/^_+/,``).toLowerCase()||`node`,n=new Set(y().nodes.map(e=>e.id)),r=t,i=2;for(;n.has(r);)r=`${t}_${i++}`;return r}function j(e=null){let t=y(),n=[...t.input_names];for(let r of t.nodes)if(r.id!==e){for(let e of r.output_ports||[`output`])n.push(`${r.id}.${e}`);(r.output_ports||[`output`]).length===1&&n.push(r.id)}return[...new Set(n)]}function M(){let e=y(),t=e.nodes.at(-1);return t?t.output_ports.length===1?t.id:`${t.id}.${t.output_ports[0]}`:e.input_names[0]}function le(e){let t=e.metadata?.inputs??e.metadata?.min_inputs??1,n={};for(let e=0;e<t;e++)n[e===0?`input`:`input_${e+1}`]=M();let r=Object.fromEntries(Object.entries(e.schema?.properties||{}).filter(([,e])=>e.default!==void 0).map(([e,t])=>[e,i(t.default)]));P(d({id:A(e.name.split(`/`).at(-1)),kind:`module`,type:e.name,inputs:n,params:r,output_ports:[`output`],call_style:`positional`,position:N()}))}function ue(e){let t=b()[0]||null,n={id:A(e),kind:e,inputs:{input:M()},output_ports:[`output`],position:N()};e===`python`&&Object.assign(n,{target:`torch.nn:Identity`,params:{},call_style:`positional`}),e===`composite`&&Object.assign(n,{template:t}),e===`repeat`&&Object.assign(n,{template:t,count:1,weights:`independent`,index_name:`index`,carry:{}}),e===`switch`&&Object.assign(n,{selector:!0,branches:{},default_branch:t}),P(d(n))}function N(){let e=y().nodes.length;return{x:270+e%6*220,y:70+Math.floor(e/6)*135}}function P(e){y().nodes.push(e);let n=y().outputs;Object.keys(n).length===1&&Object.values(n)[0]===y().input_names[0]&&(y().outputs={output:e.id}),t.selectedNode=e.id,F()}function de(e){return Object.values(y().outputs).some(t=>t===e.id||t.startsWith(`${e.id}.`))}function F(){w();let e=y();g.nodes.replaceChildren();for(let[t,n]of e.input_names.entries())I({id:n,kind:`input`,output_ports:[`output`],position:{x:25,y:60+t*100}},!0);for(let t of e.nodes)I(t,!1);R(),W(),g.status.textContent=`${e.nodes.length} node(s) · ${b().length} subgraph(s) · not validated`,g.status.classList.remove(`ra-models-valid`)}function I(e,n){let i=r(`div`,`ra-node-v2${n?` input`:``}${t.selectedNode===e.id?` selected`:``}${!n&&de(e)?` output`:``}`);i.style.left=`${e.position.x}px`,i.style.top=`${e.position.y}px`;let a=r(`h4`,null,e.label||e.id),o=r(`small`,null,n?`model input`:fe(e)),s=r(`div`,`ra-node-ports`,`out: ${(e.output_ports||[`output`]).join(`, `)}`);i.append(a,o,s),n||(i.onclick=()=>{t.selectedNode=e.id,F()},pe(a,e,i)),g.nodes.append(i)}function fe(e){return e.kind===`module`?e.type:e.kind===`python`?e.target||`Python module`:e.kind===`composite`?`Composite · ${e.template||`unset`}`:e.kind===`repeat`?`Repeat ${L(e.count)} · ${e.template||`unset`}`:e.kind===`switch`?`Switch · ${L(e.selector)}`:e.kind}function L(e){if(e&&typeof e==`object`&&Object.keys(e).length===1){if(e.$var)return`$${e.$var}`;if(e.$expr)return e.$expr}return JSON.stringify(e)}function pe(e,t,n){e.onpointerdown=r=>{e.setPointerCapture(r.pointerId);let i=r.clientX,a=r.clientY,o=t.position.x,s=t.position.y;e.onpointermove=e=>{t.position.x=Math.max(5,o+e.clientX-i),t.position.y=Math.max(5,s+e.clientY-a),n.style.left=`${t.position.x}px`,n.style.top=`${t.position.y}px`,R()},e.onpointerup=()=>e.onpointermove=null}}function R(){g.edges.replaceChildren();let e=new Map(y().input_names.map((e,t)=>[e,{x:25,y:60+t*100}]));for(let t of y().nodes)e.set(t.id,t.position);for(let t of y().nodes){let n=Array.isArray(t.inputs)?t.inputs:Object.values(t.inputs);for(let r of n){let n=r.split(`.`,1)[0],i=e.get(n);if(!i)continue;let a=document.createElementNS(`http://www.w3.org/2000/svg`,`path`),o=i.x+195,s=i.y+35,c=t.position.x,l=t.position.y+35,u=Math.max(45,Math.abs(c-o)*.4);a.setAttribute(`d`,`M${o} ${s} C${o+u} ${s},${c-u} ${l},${c} ${l}`),a.setAttribute(`class`,`ra-edge`),g.edges.append(a)}}}function z(e,t){let n=r(`label`,`field`);return n.append(r(`span`,null,e),t),n}function B(e,t=null){let n=r(`select`);for(let t of e){let e=r(`option`,null,t);e.value=t,n.append(e)}return t!==null&&(n.value=t),n}function me(e,t={}){if(t.type===`integer`){let t=Number(e);if(!Number.isInteger(t))throw Error(`Expected integer`);return t}if(t.type===`number`){let t=Number(e);if(!Number.isFinite(t))throw Error(`Expected number`);return t}if(t.type===`boolean`)return e===`true`;if(t.type===`array`||t.type===`object`||t.enum)return o(e);if(t.anyOf)try{return o(e)}catch{return e}return e}function he(e,t,n){if(t.type===`boolean`){let t=B([`true`,`false`],String(!!e));return t.onchange=()=>n(t.value===`true`),t}if(t.enum){let i=r(`select`);for(let e of t.enum){let t=r(`option`,null,String(e));t.value=JSON.stringify(e),i.append(t)}return i.value=JSON.stringify(e),i.onchange=()=>n(JSON.parse(i.value)),i}let i=t.type===`array`||t.type===`object`||typeof e==`object`,a=r(i?`textarea`:`input`);return i&&(a.className=`ra-json-editor`),a.value=i?JSON.stringify(e??t.default??null):String(e??t.default??``),a.onchange=()=>n(me(a.value,t)),a}function V(e,t,n){let a=r(`div`,`ra-binding`),o=B([`literal`,`variable`,`expression`]),s=`literal`;e&&typeof e==`object`&&Object.keys(e).length===1&&(e.$var&&(s=`variable`),e.$expr&&(s=`expression`)),o.value=s;let c=()=>{a.firstElementChild?.remove();let i;o.value===`variable`?(i=B(Object.keys(_().variables).sort(),e?.$var||Object.keys(_().variables)[0]||``),i.onchange=()=>n({$var:i.value})):o.value===`expression`?(i=r(`input`),i.placeholder=`e.g. layer_steps[layer_index]`,i.value=e?.$expr||``,i.onchange=()=>n({$expr:i.value.trim()})):i=he(e&&typeof e==`object`&&(e.$var||e.$expr)?t.default:e,t,n),a.insertBefore(i,o)};return o.onchange=()=>{if(o.value===`variable`){let t=Object.keys(_().variables)[0];if(!t)throw o.value=`literal`,Error(`Add an architecture variable first`);e={$var:t},n(e)}else o.value===`expression`?(e={$expr:``},n(e)):(e=i(t.default??``),n(e));c()},a.append(r(`span`),o),c(),a}function ge(e){g.inspector.append(r(`div`,`ra-inspector-title`,`Named inputs`)),Array.isArray(e.inputs)&&(e.inputs=Object.fromEntries(e.inputs.map((e,t)=>[t===0?`input`:`input_${t+1}`,e])));for(let[t,n]of Object.entries(e.inputs)){let i=r(`div`,`ra-input-row`),a=r(`input`);a.value=t;let o=B(j(e.id),n),s=r(`button`,`icon-button`,`×`);a.onchange=()=>{let n=a.value.trim();if(!/^[A-Za-z][A-Za-z0-9_]*$/.test(n))throw Error(`Invalid input port`);let r=Object.entries(e.inputs).map(([e,r])=>[e===t?n:e,r]);e.inputs=Object.fromEntries(r),W(),R()},o.onchange=()=>{e.inputs[t]=o.value,R()},s.onclick=()=>{delete e.inputs[t],W(),R()},i.append(a,o,s),g.inspector.append(i)}let t=r(`button`,`button compact ghost`,`Add input port`);t.onclick=()=>{let t=Object.keys(e.inputs).length+1,n=`input_${t}`;for(;Object.hasOwn(e.inputs,n);)n=`input_${++t}`;e.inputs[n]=j(e.id)[0]||y().input_names[0],W(),R()},g.inspector.append(t)}function _e(e){g.inspector.append(r(`div`,`ra-inspector-title`,`Output ports`));let t=r(`input`);t.value=e.output_ports.join(`, `),t.onchange=()=>{let n=t.value.split(`,`).map(e=>e.trim()).filter(Boolean);if(!n.length||n.some(e=>!/^[A-Za-z][A-Za-z0-9_]*$/.test(e)))throw Error(`Output ports must be comma-separated identifiers`);e.output_ports=[...new Set(n)],F()},g.inspector.append(z(`Ports`,t))}function ve(e){let t=ee(e.type);g.inspector.append(r(`div`,`ra-inspector-title`,`Module parameters`));for(let[n,r]of Object.entries(t?.schema?.properties||{})){let t=V(e.params[n],r,t=>e.params[n]=t);g.inspector.append(z(n,t))}let n=B([`auto`,`positional`,`keyword`],e.call_style);n.onchange=()=>e.call_style=n.value,g.inspector.append(z(`Call style`,n))}function ye(e){let t=r(`input`);t.value=e.target||``,t.placeholder=`package.module:Class`,t.onchange=()=>{e.target=t.value.trim(),F()},g.inspector.append(z(`Python target`,t));let n=r(`textarea`,`ra-json-editor`);n.value=JSON.stringify(e.params||{},null,2),n.onchange=()=>e.params=o(n.value,`constructor params`),g.inspector.append(z(`Constructor params`,n));let i=B([`auto`,`positional`,`keyword`],e.call_style);i.onchange=()=>e.call_style=i.value,g.inspector.append(z(`Forward call`,i))}function H(e,t=!0){let n=t?[``]:[];return n.push(...b()),B(n,e||``)}function be(e){let t=H(e.template);t.onchange=()=>{e.template=t.value||null,U(e),F()},g.inspector.append(z(`Subgraph`,t))}function xe(e){let t=H(e.template);t.onchange=()=>{e.template=t.value||null,U(e),F()},g.inspector.append(z(`Subgraph`,t)),g.inspector.append(z(`Count`,V(e.count,{type:`integer`,default:1},t=>e.count=t)));let n=B([`independent`,`shared`],e.weights);n.onchange=()=>e.weights=n.value,g.inspector.append(z(`Weights`,n));let i=r(`input`);i.value=e.index_name||`index`,i.onchange=()=>e.index_name=i.value.trim(),g.inspector.append(z(`Index variable`,i));let a=r(`textarea`,`ra-json-editor`);a.value=JSON.stringify(e.carry||{},null,2),a.placeholder=`{"feature":"feature","state":"state"}`,a.onchange=()=>e.carry=o(a.value,`carry mapping`),g.inspector.append(z(`Carry mapping`,a))}function Se(e){g.inspector.append(z(`Selector`,V(e.selector,{},t=>e.selector=t)));let t=r(`textarea`,`ra-json-editor`);t.value=JSON.stringify(e.branches||{},null,2),t.placeholder=`{"kuramoto":"kuramoto_layer","cnn":"cnn_layer","true":"enabled"}`,t.onchange=()=>e.branches=o(t.value,`branch mapping`),g.inspector.append(z(`Branches`,t));let n=H(e.default_branch);n.onchange=()=>e.default_branch=n.value||null,g.inspector.append(z(`Default branch`,n))}function U(e){let t=_().subgraphs[e.template];if(!t)return;let n=j(e.id),r=Object.values(e.inputs||{});e.inputs=Object.fromEntries(t.input_names.map((e,t)=>[e,r[t]||n[0]||y().input_names[0]])),e.output_ports=Object.keys(t.outputs)}function W(){g.inspector.replaceChildren();let e=y().nodes.find(e=>e.id===t.selectedNode);if(!e){g.inspector.textContent=`Select a module or control node.`;return}let n=r(`input`);n.value=e.label||``,n.onchange=()=>{e.label=n.value.trim()||null,F()},g.inspector.append(z(`Label`,n));let i=r(`input`);i.value=e.id,i.onchange=()=>Ce(e,i.value.trim()),g.inspector.append(z(`Node id`,i)),ge(e),_e(e),e.kind===`module`&&ve(e),e.kind===`python`&&ye(e),e.kind===`composite`&&be(e),e.kind===`repeat`&&xe(e),e.kind===`switch`&&Se(e),g.inspector.append(r(`div`,`ra-inspector-title`,`Expose graph outputs`));for(let t of e.output_ports){let n=e.output_ports.length===1?e.id:`${e.id}.${t}`,i=Object.entries(y().outputs).find(([,e])=>e===n),a=r(`div`,`ra-output-row`),o=r(`input`);o.type=`checkbox`,o.checked=!!i;let s=r(`input`);s.value=i?.[0]||t,s.disabled=!o.checked,o.onchange=()=>{o.checked?y().outputs[s.value||t]=n:i&&delete y().outputs[i[0]],F()},s.onchange=()=>{o.checked&&(i&&delete y().outputs[i[0]],y().outputs[s.value.trim()]=n,F())},a.append(o,s,r(`code`,null,n)),g.inspector.append(a)}let a=r(`button`,`button compact ghost danger`,`Delete node`);a.onclick=()=>we(e),g.inspector.append(a)}function Ce(e,n){if(!/^[A-Za-z][A-Za-z0-9_-]*$/.test(n))throw Error(`Invalid node id`);if(n!==e.id&&y().nodes.some(e=>e.id===n))throw Error(`Node ${n} already exists`);let r=e.id;e.id=n;let i=e=>e===r?n:e.startsWith(`${r}.`)?`${n}${e.slice(r.length)}`:e;for(let e of y().nodes)Array.isArray(e.inputs)?e.inputs=e.inputs.map(i):e.inputs=Object.fromEntries(Object.entries(e.inputs).map(([e,t])=>[e,i(t)]));y().outputs=Object.fromEntries(Object.entries(y().outputs).map(([e,t])=>[e,i(t)])),t.selectedNode=n,F()}function we(e){y().nodes=y().nodes.filter(t=>t.id!==e.id);let n=t=>t===e.id||t.startsWith(`${e.id}.`);for(let e of y().nodes)Array.isArray(e.inputs)?e.inputs=e.inputs.filter(e=>!n(e)):e.inputs=Object.fromEntries(Object.entries(e.inputs).filter(([,e])=>!n(e)));y().outputs=Object.fromEntries(Object.entries(y().outputs).filter(([,e])=>!n(e))),Object.keys(y().outputs).length||(y().outputs={output:y().input_names[0]}),t.selectedNode=null,F()}function G(){let e=g.templateInputs.value.split(`,`).map(e=>e.trim()).filter(Boolean);if(!e.length||e.some(e=>!/^[A-Za-z][A-Za-z0-9_]*$/.test(e)))throw Error(`Template input ports must be comma-separated identifiers`);y().input_names=[...new Set(e)];let t=o(g.templateOutputs.value,`output mapping`);if(!t||Array.isArray(t)||typeof t!=`object`||!Object.keys(t).length)throw Error(`Template outputs must be a non-empty JSON mapping`);y().outputs=t}async function K(){ne(),G(),S();let e=await s(`/api/torch/parameterized-graph/validate`,{method:`POST`,body:JSON.stringify({params:_()})});return g.status.textContent=`Valid architecture · ${e.nodes} total nodes · ${e.subgraphs} subgraphs · ${e.variables} variables`,g.status.classList.add(`ra-models-valid`),e}async function Te(){await K();let e=g.path.value.trim();if(!/^architectures\/.+\.json$/.test(e))throw Error(`Architecture path must be architectures/*.json`);let n=`${JSON.stringify(t.document,null,2)}\n`,r=await s(`/api/files?path=${encodeURIComponent(e)}`,{method:`PUT`,body:JSON.stringify({content:n,revision:e===t.path?t.revision:null})});t.path=e,t.revision=r.revision,await J(),g.status.textContent=`Saved ${e}`}async function Ee(n){let r=await s(`/api/files?path=${encodeURIComponent(n)}`);t.document=u(JSON.parse(r.content)),t.path=n,t.revision=r.revision,t.activeTemplate=e,t.selectedNode=t.document.graph.nodes[0]?.id||null,q()}function De(){t.document=l(),t.path=null,t.revision=null,t.activeTemplate=e,t.selectedNode=null,q()}function q(){te(),D(),w(),k(),F()}async function J(){t.bootstrap=await s(`/api/bootstrap`);let e=await s(`/api/architectures`);t.files=e.architectures,C(),k(),Q()}async function Y(){S(),await J(),q(),h.showModal()}function X(e,t){if(!e)return!0;let n=e.trim(),r=n.split(/\s+(?:or|\|\|)\s+/);if(r.length>1)return r.some(e=>X(e,t));let i=n.split(/\s+(?:and|&&)\s+/);if(i.length>1)return i.every(e=>X(e,t));if(n.startsWith(`not `))return!X(n.slice(4),t);let a=n.match(/^([A-Za-z][A-Za-z0-9_]*)\s*(==|!=)\s*(.+)$/);if(a){let[,e,n,r]=a,i;try{i=JSON.parse(r.replaceAll(`'`,`"`))}catch{i=r.trim()}return n===`==`?t[e]===i:t[e]!==i}return!!t[n]}function Oe(e,t,n){let i=t.variable_specs?.[e]||{type:O(t.variables[e])},a=t.variables[e];if(i.type===`bool`){let e=r(`input`);return e.type=`checkbox`,e.checked=!!a,e.onchange=()=>n(e.checked),e}if(i.type===`enum`){let e=r(`select`);for(let t of i.choices||[]){let n=r(`option`,null,String(t));n.value=JSON.stringify(t),e.append(n)}return e.value=JSON.stringify(a),e.onchange=()=>n(JSON.parse(e.value)),e}let s=r(`input`);return i.type===`int`||i.type===`float`?(s.type=`number`,s.step=i.type===`int`?`1`:`any`,s.value=String(a),s.onchange=()=>n(Number(s.value))):i.type===`string`?(s.value=a||``,s.onchange=()=>n(s.value)):(s.value=JSON.stringify(a),s.onchange=()=>n(o(s.value))),s}function Z(e){let i=n(`.component-type`,e),a=n(`.schema-fields`,e);if(!i||!a||i.value!==`torch/parameterized-graph`||n(`.ra-config-architecture`,a))return;a.dataset.editor=`torch-graph`;let o=r(`div`,`ra-config-architecture`),c=r(`select`),l=r(`option`,null,`Select saved architecture…`);l.value=``,c.append(l);for(let e of t.files){let t=r(`option`,null,e.path);t.value=e.path,c.append(t)}let d=r(`button`,`button compact ghost`,`Open Models`),f=r(`div`),p=r(`div`,`architecture-empty`,`Select an architecture; variables remain matrix/override targets.`);d.onclick=()=>Y().catch(x),c.onchange=async()=>{if(c.value)try{let e=await s(`/api/files?path=${encodeURIComponent(c.value)}`),t=u(JSON.parse(e.content)).graph;a.dataset.graph=JSON.stringify(t);let n=()=>{f.replaceChildren();for(let e of Object.keys(t.variables).sort()){let i=t.variable_specs?.[e]||{},o=r(`div`,`ra-config-variable`),s=r(`strong`,null,e),c=Oe(e,t,r=>{t.variables[e]=r,a.dataset.graph=JSON.stringify(t),n()}),l=r(`code`,null,`components.model.params.variables.${e}`);X(i.enabled_if,t.variables)||(o.classList.add(`disabled`),c.disabled=!0),o.append(s,c,l),f.append(o)}};n(),p.textContent=`${t.nodes.length} root nodes · ${Object.keys(t.subgraphs||{}).length} subgraphs · ${Object.keys(t.variables).length} variables`}catch(e){p.textContent=e.message}},o.append(c,d,f,p),a.replaceChildren(o)}function Q(){let e=n(`#creator-components`);if(e)for(let t of e.querySelectorAll(`.component-item`)){let e=n(`.component-type`,t);if(!e)continue;let r=[...e.options].find(e=>e.value===`torch/parameterized-graph`);r&&(r.textContent=`torch/parameterized-graph (advanced saved architecture)`),e.dataset.raArchitectureV2||(e.dataset.raArchitectureV2=`1`,e.addEventListener(`change`,()=>queueMicrotask(()=>Z(t)))),Z(t)}}p.onclick=()=>Y().catch(x),n(`#ra-close-models`,h).onclick=()=>h.close(),n(`#ra-new-architecture`,h).onclick=De,n(`#ra-add-variable`,h).onclick=()=>{try{oe()}catch(e){x(e)}},n(`#ra-new-subgraph`,h).onclick=n(`#ra-new-subgraph-side`,h).onclick=()=>{try{re()}catch(e){x(e)}},n(`#ra-delete-subgraph`,h).onclick=()=>{try{ie()}catch(e){x(e)}},g.activeTemplate.onchange=()=>T(g.activeTemplate.value),g.templateInputs.onchange=()=>{try{G(),F()}catch(e){x(e)}},g.templateOutputs.onchange=g.templateInputs.onchange,g.architectureFilter.oninput=C,g.paletteFilter.oninput=k,n(`#ra-validate-model`,h).onclick=()=>K().catch(x),n(`#ra-save-model`,h).onclick=()=>Te().catch(x);for(let e of[`new-config-button`,`empty-create-button`])n(`#${e}`)?.addEventListener(`click`,()=>J().then(()=>setTimeout(Q)).catch(()=>{}));let $=n(`#creator-components`);$&&new MutationObserver(()=>setTimeout(Q)).observe($,{childList:!0,subtree:!0}),J().catch(()=>{})}var n=`researchAssistantUnifiedWorkbenchThemeV1`;function r(){if(globalThis[n])return;globalThis[n]=!0;let e=document.createElement(`style`);e.id=`ra-unified-workbench-theme`,e.textContent=`
    :root{
      --ra-panel:#111816;
      --ra-panel-raised:#17201e;
      --ra-panel-soft:#0e1412;
      --ra-panel-deep:#0c1110;
      --ra-border:#27352f;
      --ra-border-strong:#385047;
      --ra-text:#d9e4df;
      --ra-muted:#82938c;
      --ra-faint:#52645e;
      --ra-accent:#7ce5b2;
      --ra-accent-strong:#38c985;
      --ra-accent-ink:#07130e;
      --ra-danger:#ff8c84;
      --ra-warning:#f3ca78;
      --ra-radius:8px;
      --ra-radius-large:12px;
      --ra-shadow:0 30px 100px #000a;
    }

    .topbar{
      position:relative;
      z-index:40;
      grid-template-columns:270px minmax(180px,1fr) auto;
    }
    .topbar-actions{
      position:relative;
      z-index:41;
      min-width:0;
      gap:7px;
      overflow:visible;
    }
    .workbench{grid-template-columns:270px minmax(0,1fr) !important}
    .editor-column{grid-column:2;width:100%;min-width:0;overflow:hidden}
    .tabs{grid-row:1}
    .empty-state,.editor{grid-row:2;grid-column:1}
    .output-panel{grid-row:3}
    .editor{display:block;width:100%;height:100%;min-width:0;min-height:0}
    .editor[hidden]{display:none}
    .editor>.monaco-editor{width:100% !important;height:100% !important}
    .registry-panel{display:none !important;grid-column:3}
    .workbench.ra-registry-open{grid-template-columns:270px minmax(0,1fr) 310px !important}
    .workbench.ra-registry-open .registry-panel{display:block !important}
    .ra-registry-controls{display:flex;align-items:center;gap:6px}
    @media(max-width:1180px){
      .workbench.ra-registry-open{grid-template-columns:240px minmax(0,1fr) !important}
      .workbench.ra-registry-open .registry-panel{position:fixed;z-index:60;top:54px;right:0;bottom:24px;display:block !important;width:310px;box-shadow:-18px 0 50px #0009}
    }
    .ra-section-nav{
      display:flex;
      max-width:min(620px,48vw);
      align-items:center;
      gap:2px;
      overflow-x:auto;
      scrollbar-width:none;
      padding:3px;
      border:1px solid var(--border);
      border-radius:9px;
      background:#0a100e;
    }
    .ra-section-nav::-webkit-scrollbar{display:none}
    .ra-section-nav>.button{
      min-height:27px;
      padding:0 10px;
      border-color:transparent;
      background:transparent;
      color:var(--muted);
      font-size:11px;
    }
    .ra-section-nav>.button:hover:not(:disabled){
      border-color:var(--border);
      color:var(--text);
      background:var(--surface-raised);
    }
    .ra-more-menu{
      position:relative;
    }
    .ra-more-menu>summary{
      display:flex;
      min-height:32px;
      align-items:center;
      gap:7px;
      padding:0 12px;
      list-style:none;
    }
    .ra-more-menu>summary::-webkit-details-marker{display:none}
    .ra-more-menu>summary::after{
      content:"";
      width:6px;
      height:6px;
      border-right:1px solid currentColor;
      border-bottom:1px solid currentColor;
      transform:translateY(-2px) rotate(45deg);
    }
    .ra-more-menu[open]>summary{
      border-color:var(--accent-strong);
      color:var(--text);
      background:var(--surface-raised);
    }
    .ra-more-popover{
      position:absolute;
      z-index:2000;
      top:39px;
      right:0;
      display:grid;
      width:190px;
      padding:6px;
      border:1px solid var(--border-bright);
      border-radius:9px;
      background:var(--surface);
      box-shadow:0 18px 55px #000b;
    }
    .ra-more-popover>.button{
      justify-content:flex-start;
      width:100%;
      min-height:32px;
      border:0;
      background:transparent;
      text-align:left;
    }

    dialog.raX,
    dialog.raPipe,
    dialog.raResearch,
    dialog.ra-models-v2{
      padding:0 !important;
      overflow:hidden !important;
      border:1px solid var(--border-bright) !important;
      border-radius:var(--ra-radius-large) !important;
      color:var(--text) !important;
      background:var(--surface) !important;
      box-shadow:var(--ra-shadow) !important;
    }
    dialog.raX::backdrop,
    dialog.raPipe::backdrop,
    dialog.raResearch::backdrop,
    dialog.ra-models-v2::backdrop{
      background:#050807cc !important;
      backdrop-filter:blur(3px);
    }
    dialog.raX{width:min(1440px,calc(100vw - 40px)) !important;height:min(880px,calc(100vh - 40px)) !important}
    dialog.raPipe{width:min(1320px,calc(100vw - 40px)) !important;height:min(850px,calc(100vh - 40px)) !important}
    dialog.raResearch{width:min(1380px,calc(100vw - 40px)) !important;height:min(880px,calc(100vh - 40px)) !important}
    dialog.ra-models-v2{width:min(1580px,calc(100vw - 32px)) !important;height:min(920px,calc(100vh - 32px)) !important}

    .raH,.raPipeH,.raRH,.ra-models-heading{
      display:flex !important;
      min-height:66px;
      align-items:center !important;
      justify-content:space-between !important;
      gap:14px;
      padding:14px 18px !important;
      border-bottom:1px solid var(--border) !important;
      background:linear-gradient(180deg,#131b18 0%,var(--surface) 100%) !important;
    }
    .ra-dialog-title{
      min-width:0;
    }
    .ra-dialog-title .eyebrow{
      display:block;
      margin-bottom:4px;
    }
    .ra-dialog-title h2,
    .ra-models-heading h2{
      margin:0 !important;
      color:var(--text);
      font-size:19px !important;
      font-weight:650;
      letter-spacing:-.03em;
    }

    .raH>.raB[data-close],
    .raPipeH>.raPipeB[data-pipe-close],
    .raRH>.raRB[data-research-close]{
      display:grid !important;
      width:28px !important;
      height:28px !important;
      min-height:28px !important;
      padding:0 !important;
      place-items:center;
      border:1px solid var(--border-bright) !important;
      border-radius:7px !important;
      color:var(--muted) !important;
      background:var(--surface-raised) !important;
      font-size:18px;
    }

    .raB,.raPipeB,.raRB{
      min-height:31px !important;
      padding:0 11px !important;
      border:1px solid var(--border-bright) !important;
      border-radius:7px !important;
      color:var(--text) !important;
      background:var(--surface-raised) !important;
      font-size:11px !important;
      font-weight:600;
    }
    .raB:hover:not(:disabled),.raPipeB:hover:not(:disabled),.raRB:hover:not(:disabled){
      border-color:#557267 !important;
      background:var(--surface-hover) !important;
    }
    .raB.ra-theme-primary,.raPipeB.ra-theme-primary,.raRB.ra-theme-primary{
      border-color:var(--accent) !important;
      color:var(--accent-ink) !important;
      background:var(--accent) !important;
    }
    .raB:disabled,.raPipeB:disabled,.raRB:disabled{opacity:.42}

    .raTabs,.raPipeTabs,.raRTabs{
      display:flex !important;
      min-height:43px;
      align-items:end;
      gap:0 !important;
      padding:0 14px !important;
      overflow-x:auto;
      border-bottom:1px solid var(--border) !important;
      background:#0f1513 !important;
    }
    .raTabs .raB,.raPipeTabs .raPipeB,.raRTabs .raRB{
      position:relative;
      min-height:42px !important;
      padding:0 13px !important;
      border:0 !important;
      border-radius:0 !important;
      color:var(--muted) !important;
      background:transparent !important;
      font-size:11px !important;
      white-space:nowrap;
    }
    .raTabs .raB::after,.raPipeTabs .raPipeB::after,.raRTabs .raRB::after{
      position:absolute;
      right:10px;
      bottom:-1px;
      left:10px;
      height:2px;
      content:"";
      background:transparent;
    }
    .raTabs .raB.active,.raPipeTabs .raPipeB.active,.raRTabs .raRB.active{
      color:var(--text) !important;
    }
    .raTabs .raB.active::after,.raPipeTabs .raPipeB.active::after,.raRTabs .raRB.active::after{
      background:var(--accent);
    }

    .raG{
      display:grid !important;
      height:calc(100% - 66px) !important;
      grid-template-columns:320px minmax(0,1fr) !important;
      background:var(--border) !important;
      gap:1px !important;
    }
    .raS,.raM,.raPipeMain,.raRMain{
      color:var(--text) !important;
      background:var(--surface) !important;
    }
    .raS{
      padding:14px !important;
      border-right:0 !important;
      background:#0e1412 !important;
    }
    .raM{
      padding:16px !important;
    }
    .raPipeMain,.raRMain{
      height:calc(100% - 109px) !important;
      padding:16px 18px !important;
    }

    .raF,.raPipeField,.raRField{
      display:flex !important;
      min-width:0;
      flex-direction:column;
      gap:5px !important;
      margin-bottom:10px !important;
      color:var(--muted);
      font-size:10px !important;
    }
    .raF input,.raF textarea,.raF select,
    .raInline input,.raInline select,
    .raPipeField input,.raPipeField textarea,.raPipeField select,
    .raRField input,.raRField textarea,.raRField select,
    .raPipeActions input,.raRActions input,
    .ra-models-v2 input,.ra-models-v2 textarea,.ra-models-v2 select{
      border:1px solid var(--border) !important;
      border-radius:6px !important;
      outline:none;
      color:var(--text) !important;
      background:#0e1412 !important;
      font:inherit;
    }
    .raF input,.raF select,.raInline input,.raInline select,
    .raPipeField input,.raPipeField select,.raRField input,.raRField select,
    .raPipeActions input,.raRActions input,
    .ra-models-v2 input,.ra-models-v2 select{
      height:34px;
      padding:0 9px !important;
    }
    .raF textarea,.raPipeField textarea,.raRField textarea,.ra-models-v2 textarea{
      padding:8px 9px !important;
      font-family:"SFMono-Regular",Consolas,monospace !important;
      font-size:11px !important;
      line-height:1.5;
    }
    .raF input:focus,.raF textarea:focus,.raF select:focus,
    .raPipeField input:focus,.raPipeField textarea:focus,.raPipeField select:focus,
    .raRField input:focus,.raRField textarea:focus,.raRField select:focus,
    .ra-models-v2 input:focus,.ra-models-v2 textarea:focus,.ra-models-v2 select:focus{
      border-color:var(--accent-strong) !important;
      box-shadow:0 0 0 2px #38c98522;
    }

    .raC,.raCard,.raChart,.raPipeCard,.raRCard,.ra-config-architecture{
      border:1px solid var(--border) !important;
      border-radius:8px !important;
      color:var(--text) !important;
      background:#0f1513 !important;
      box-shadow:none !important;
    }
    .raC{
      margin:6px 0 !important;
      padding:10px !important;
    }
    .raC:hover,.raC.sel{
      border-color:#416857 !important;
      background:var(--surface-raised) !important;
    }
    .raC.sel{box-shadow:inset 2px 0 0 var(--accent) !important}
    .raCard,.raChart,.raPipeCard,.raRCard{padding:11px !important}
    .raPipeGrid,.raRGrid,.raCards,.raCharts{
      gap:10px !important;
    }

    .raP,.raPipeCode,.raRCode{
      border:1px solid var(--border) !important;
      border-radius:7px !important;
      color:#a8bbb3 !important;
      background:#0c1110 !important;
      font-family:"SFMono-Regular",Consolas,monospace !important;
      font-size:10px !important;
      line-height:1.55;
    }
    .raP,.raPipeCode,.raRCode{padding:11px !important}

    .raT,.raPipeTable,.raRTable{
      width:100%;
      border-collapse:collapse;
      color:var(--text);
      font-size:11px !important;
    }
    .raT th,.raT td,.raPipeTable th,.raPipeTable td,.raRTable th,.raRTable td{
      padding:8px 9px !important;
      border-bottom:1px solid var(--border) !important;
      text-align:left;
      vertical-align:top;
    }
    .raT th,.raPipeTable th,.raRTable th{
      color:var(--muted);
      background:#0f1513 !important;
      font-size:9px;
      font-weight:700;
      letter-spacing:.08em;
      text-transform:uppercase;
    }

    .raMuted,.raPipeMuted,.raRMuted{color:var(--muted) !important}
    .raE,.raPipeError,.raRError,.ra-models-error{color:var(--danger) !important}
    .raGood{color:var(--accent) !important}.raWarn{color:var(--warning) !important}.raBad{color:var(--danger) !important}
    .raStatus.running,.raStatus.queued,.raStatus.pending{color:var(--warning) !important}
    .raStatus.completed{color:var(--accent) !important}

    .raLiveControls{
      border-color:var(--border) !important;
      border-radius:8px !important;
      background:#0e1412 !important;
    }
    .raMetricChoice{
      border-color:var(--border) !important;
      background:var(--surface) !important;
    }
    .raRunTable{
      border-color:var(--border) !important;
      border-radius:8px !important;
    }
    .raEmpty{
      border-color:var(--border-bright) !important;
      color:var(--muted) !important;
    }

    .ra-models-layout{background:var(--border) !important;gap:1px}
    .ra-models-sidebar,.ra-palette,.ra-inspector{
      border-color:var(--border) !important;
      background:#0e1412 !important;
    }
    .ra-models-main{background:var(--surface) !important}
    .ra-models-meta,.ra-template-bar,.ra-variable-panel,.ra-models-footer{
      border-color:var(--border) !important;
      background:var(--surface) !important;
    }
    .ra-models-meta{padding:12px 14px !important}
    .ra-template-bar{padding:10px 14px !important}
    .ra-variable-panel{padding:9px 14px !important}
    .ra-models-work{background:var(--border) !important;gap:1px}
    .ra-palette-button{
      border-color:transparent !important;
      border-radius:6px !important;
      background:transparent !important;
    }
    .ra-palette-button:hover{
      border-color:var(--border) !important;
      background:var(--surface-hover) !important;
    }
    .ra-canvas-scroll{
      background-color:#101514 !important;
      background-image:radial-gradient(#38504777 1px,transparent 1px) !important;
    }
    .ra-edge{stroke:var(--accent-strong) !important}
    .ra-node-v2{
      border-color:var(--border-bright) !important;
      background:var(--surface-raised) !important;
      box-shadow:0 9px 22px #0007 !important;
    }
    .ra-node-v2.selected{border-color:var(--accent) !important;box-shadow:0 0 0 2px #38c98522,0 9px 22px #0007 !important}
    .ra-node-v2.output{border-color:#4c9f77 !important}
    .ra-node-v2.input{background:#12231c !important}
    .ra-template-list button,.ra-architecture-list button{
      border-radius:6px !important;
      color:var(--muted) !important;
    }
    .ra-template-list button:hover,.ra-architecture-list button:hover,
    .ra-template-list button.active,.ra-architecture-list button.active{
      border-color:var(--border) !important;
      color:var(--text) !important;
      background:var(--surface-hover) !important;
    }
    .ra-template-list button.active,.ra-architecture-list button.active{
      box-shadow:inset 2px 0 0 var(--accent);
    }

    @media(max-width:1180px){
      .workspace-heading{display:none}
      .topbar{grid-template-columns:240px minmax(0,1fr)}
      .ra-section-nav>.button{padding:0 8px}
      .raG{grid-template-columns:280px minmax(0,1fr) !important}
      .ra-models-layout{grid-template-columns:210px minmax(0,1fr) !important}
      .ra-models-work{grid-template-columns:210px minmax(0,1fr) 315px !important}
    }
    @media(max-width:900px){
      .brand-name,.mvp-badge{display:none}
      .brand{padding:0 10px}
      .topbar{grid-template-columns:58px minmax(0,1fr)}
      .ra-section-nav{max-width:48vw}
      .ra-more-menu{display:block}
      .raG{grid-template-columns:1fr !important}
      .raS{display:none}
      .raRGrid{grid-template-columns:1fr !important}
      .ra-models-sidebar{display:none}
      .ra-models-layout{grid-template-columns:1fr !important}
      .ra-models-work{grid-template-columns:190px minmax(0,1fr) !important}
      .ra-inspector{display:none}
    }
  `,document.head.append(e);let t=new Set([`Start`,`Build`,`Build bundle`,`Create`,`Register`,`Analyze`,`Propose + launch`,`Evaluate selected runs`,`Create immutable lock`,`Save`,`Validate`,`Run`,`Launch`]);function r(e){if(!e||e.dataset.raThemeReady===`1`)return;e.dataset.raThemeReady=`1`;let n=e.querySelector(`.raH,.raPipeH,.raRH`);if(n){let t=n.querySelector(`b`);if(t){let n=document.createElement(`div`);n.className=`ra-dialog-title`;let r=document.createElement(`span`);r.className=`eyebrow`;let i=document.createElement(`h2`),a={"ra-jobs":[`EXECUTION`,`Jobs and live metrics`],"ra-charts":[`ANALYTICS`,`Advanced charts`],"ra-pipeline":[`OPERATIONS`,`Research pipeline`],"ra-research":[`RESEARCH`,`End-to-end research`]}[e.id]||[`WORKBENCH`,t.textContent];r.textContent=a[0],i.textContent=a[1],n.append(r,i),t.replaceWith(n)}}e.querySelectorAll(`.raB,.raPipeB,.raRB`).forEach(e=>{let n=e.textContent.trim();t.has(n)&&e.classList.add(`ra-theme-primary`)})}let i=`research-assistant.registry-open.v1`;function a(){return document.querySelector(`.workbench`)?.classList.contains(`ra-registry-open`)||!1}function o(){let e=document.querySelector(`#ra-registry-toggle`);if(!e)return;let t=a();e.textContent=t?`Hide Registry`:`Registry`,e.setAttribute(`aria-pressed`,String(t))}function s(e,t=!0){let n=document.querySelector(`.workbench`),r=document.querySelector(`.registry-panel`);if(!n||!r)return;let s=a()!==e||r.hidden===e;if(n.classList.toggle(`ra-registry-open`,e),r.hidden=!e,r.setAttribute(`aria-hidden`,String(!e)),t)try{localStorage.setItem(i,e?`1`:`0`)}catch{}o(),s&&requestAnimationFrame(()=>window.dispatchEvent(new Event(`resize`)))}function c(){let e=document.querySelector(`.registry-panel`),t=e?.querySelector(`.panel-heading`);if(!e||!t)return;let n=t.querySelector(`.ra-registry-controls`);if(!n){n=document.createElement(`span`),n.className=`ra-registry-controls`;let e=t.querySelector(`#component-count`);e&&n.append(e);let r=document.createElement(`button`);r.type=`button`,r.className=`icon-button`,r.setAttribute(`aria-label`,`Hide Registry`),r.textContent=`×`,r.addEventListener(`click`,()=>s(!1)),n.append(r),t.append(n)}let r=!1;try{r=localStorage.getItem(i)===`1`}catch{}s(r,!1)}function l(){let e=document.querySelector(`.topbar-actions`);if(!e)return;let t=new Map([[`Jobs+`,`Jobs`],[`Charts+`,`Charts`],[`Pipeline+`,`Pipeline`],[`Research+`,`Research`]]);[...e.querySelectorAll(`button`)].forEach(e=>{let n=e.textContent.trim();t.has(n)&&(e.textContent=t.get(n))});let n=e.querySelector(`.ra-section-nav`);n||(n=document.createElement(`nav`),n.className=`ra-section-nav`,n.setAttribute(`aria-label`,`Research workspaces`));let r=e.querySelector(`.ra-more-menu`);if(!r){r=document.createElement(`details`),r.className=`ra-more-menu`;let e=document.createElement(`summary`);e.className=`button ghost`,e.textContent=`More`;let t=document.createElement(`div`);t.className=`ra-more-popover`,r.append(e,t)}let i=r.querySelector(`.ra-more-popover`);i.dataset.raCloseBound!==`1`&&(i.dataset.raCloseBound=`1`,i.addEventListener(`click`,e=>{e.target.closest(`button`)&&r.removeAttribute(`open`)}));let c=e.querySelector(`#ra-registry-toggle`);c||(c=document.createElement(`button`),c.id=`ra-registry-toggle`,c.type=`button`,c.className=`button ghost`,c.textContent=`Registry`,c.addEventListener(`click`,()=>s(!a())),e.append(c)),o();let l=[`Models`,`Launch`,`Jobs`,`Pipeline`,`Research`,`Reports`],u=[`Registry`,`Charts`,`Checkpoints`,`Project`,`New file`],d=[...e.querySelectorAll(`:scope > button`)],f=new Map(d.map(e=>[e.textContent.trim(),e]));for(let e of l){let t=f.get(e);t&&n.append(t)}for(let e of u){let t=f.get(e);t&&(i.append(t),t.addEventListener(`click`,()=>r.removeAttribute(`open`),{once:!1}))}let p=f.get(`New config`),m=f.get(`Inspect`),h=f.get(`Save`),g=new Set([...l,...u,`New config`,`Inspect`,`Save`]);for(let e of d)g.has(e.textContent.trim())||i.append(e);e.replaceChildren(),p&&e.append(p),e.append(n,r),m&&e.append(m),h&&e.append(h)}function u(){f.disconnect(),document.querySelectorAll(`dialog.raX,dialog.raPipe,dialog.raResearch,dialog.ra-models-v2`).forEach(r),c(),l(),f.observe(document.documentElement,{childList:!0,subtree:!0})}let d=!1,f=new MutationObserver(e=>{let t=document.querySelector(`.topbar-actions`);!e.some(e=>e.target===t||[...e.addedNodes].some(e=>e.nodeType===Node.ELEMENT_NODE&&(e.matches?.(`dialog`)||e.querySelector?.(`dialog`))))||d||(d=!0,requestAnimationFrame(()=>{d=!1,u()}))});u()}function i(){document.readyState===`loading`?document.addEventListener(`DOMContentLoaded`,()=>setTimeout(r,0),{once:!0}):setTimeout(r,0)}i();