"use strict";
// DOM semantics in jsdom, with explicit simulated visibility. This is not a
// claim of Firefox execution, browser sandbox validation or a real login.
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {JSDOM} = require(process.env.SENTRA_QA_JSDOM);
const root = process.env.SENTRA_QA_EXTENSION_DIR;
const source = fs.readFileSync(path.join(root, "firefox/dom.js"), "utf8");
test("packaged injection finishes with a cloneable value", () => {
  const environment = new JSDOM("<main></main>", {url:"https://platform.openai.com/settings/organization/tunnels",runScripts:"outside-only"});
  const completion=environment.window.eval(source);
  assert.doesNotThrow(()=>structuredClone(completion));
  assert.equal(typeof environment.window.SentraEnrollmentDom,"function");
  environment.window.close();
});
function dom(html, route="tunnels", origin="https://platform.openai.com") {
  const environment = new JSDOM(html, {url: origin + "/settings/organization/" + route, runScripts: "outside-only"});
  const window = environment.window;
  Object.defineProperty(window.HTMLElement.prototype,"innerText",{get(){return this.textContent;}});
  window.HTMLElement.prototype.getClientRects = function() {
    return this.hidden || this.closest("[hidden]") || this.style.display === "none" ? [] : [{}];
  };
  window.eval(source);
  return {window, run: command => JSON.parse(JSON.stringify(window.SentraEnrollmentDom({operation: "dom", ...command})))};
}

test("native project selection sends form events and returns labels without option values", () => {
  const {window, run} = dom('<label for="project">Project</label><select id="project"><option value="">Select project...</option><option value="private-project-id">Default project</option></select><button id="create" disabled>Create secret key</button>',"api-keys");
  const events=[];
  window.document.querySelector("select").addEventListener("input",()=>events.push("input"));
  window.document.querySelector("select").addEventListener("change",()=>{
    events.push("change");window.document.querySelector("#create").disabled=false;
  });
  const result=run({steps:[{kind:"css",selector:"select"}],action:"select_label",label:"Default project"});
  assert.deepEqual(result,{ok:true,result:"Default project"});
  assert.equal(window.document.querySelector("select").value,"private-project-id");
  assert.equal(window.document.querySelector("#create").disabled,false);
  assert.deepEqual(events,["input","change"]);
  assert.equal(JSON.stringify(result).includes("private-project-id"),false);
  assert.equal(run({steps:[{kind:"css",selector:"select option:checked"}],action:"text"}).result,"Default project");
  window.close();
});

test("native selection rejects disabled, ambiguous and unrelated controls", () => {
  const {window,run}=dom('<select id="disabled" disabled><option>Never</option></select><select id="ambiguous"><option>Never</option><option>Never</option></select><input id="other" value="unchanged"><select id="option"><option>Before</option><option disabled>Never</option></select>',"api-keys");
  for(const [id,code] of [["disabled","bridge_element_disabled"],["ambiguous","bridge_selector_ambiguous"],["other","bridge_element_disabled"],["option","bridge_element_disabled"]])
    assert.equal(run({steps:[{kind:"css",selector:"#"+id}],action:"select_label",label:"Never"}).error,code);
  assert.equal(window.document.querySelector("#other").value,"unchanged");
  assert.equal(window.document.querySelector("#option").value,"Before");
  window.close();
});

test("custom selectors receive pointerdown and pointerup without client coordinates", () => {
  const {window,run}=dom('<button id="project">Select project...</button><div id="menu" hidden><div role="option">Default project</div></div>',"api-keys");
  window.PointerEvent = class extends window.MouseEvent {
    constructor(type, options) { super(type, options); Object.defineProperty(this,'pointerType',{value:options.pointerType}); }
  };
  const trigger=window.document.querySelector('#project'), menu=window.document.querySelector('#menu');
  const events=[];
  trigger.addEventListener('pointerdown',event=>{events.push(event.type); assert.equal(event.pointerType,'mouse'); menu.hidden=false; event.preventDefault();});
  trigger.addEventListener('mousedown',()=>events.push('mousedown'));
  trigger.addEventListener('click',()=>events.push('click'));
  menu.querySelector('[role="option"]').addEventListener('pointerup',()=>{trigger.textContent='Default project';menu.hidden=true;});
  assert.equal(run({steps:[{kind:'css',selector:'#project'}],action:'pointer_click',clientX:999999}).ok,true);
  assert.equal(menu.hidden,false);
  assert.deepEqual(events,['pointerdown','click']);
  assert.equal(run({steps:[{kind:'role',role:'option'}],action:'pointer_click'}).ok,true);
  assert.equal(trigger.textContent,'Default project');
  assert.equal(menu.hidden,true);
  trigger.disabled=true;
  assert.equal(run({steps:[{kind:'css',selector:'#project'}],action:'pointer_click'}).error,'bridge_element_disabled');
  window.close();
});
test("accessible labels, fill events and visible dialog deduplication", () => {
  const {window, run} = dom('<section role="dialog" aria-modal="true"><label for="name">Nome</label><input id="name"><button aria-label="Criar tunnel">+</button></section>');
  const dialogs = [{kind:"css", selector:'[role="dialog"]:visible, [aria-modal="true"]:visible'}];
  assert.equal(run({steps:dialogs, action:"count"}).result, 1);
  const field = [...dialogs, {kind:"role", role:"textbox", name:{source:"name|nome",flags:"i"}}];
  const events=[]; window.document.querySelector("input").addEventListener("input", () => events.push("input"));
  window.document.querySelector("input").addEventListener("change", () => events.push("change"));
  assert.equal(run({steps:field, action:"fill", value:"SENTRA-fixture"}).ok, true);
  assert.equal(window.document.querySelector("input").value,"SENTRA-fixture");
  assert.deepEqual(events,["input","change"]);
  assert.equal(run({steps:[{kind:"role",role:"button",name:{source:"^criar tunnel$",flags:"i"}}],action:"count"}).result,1);
  window.close();
});
test("ambiguity and disabled/password inputs do not produce effects", () => {
  const {window, run} = dom('<button>Create</button><button>Create</button><input type="password"><input readonly>');
  let clicks=0; window.document.addEventListener("click",()=>clicks++);
  assert.equal(run({steps:[{kind:"role",role:"button"}],action:"click"}).error,"bridge_selector_ambiguous");
  assert.equal(clicks,0);
  for(const selector of ['input[type="password"]','input[readonly]'])
    assert.equal(run({steps:[{kind:"css",selector}],action:"fill",value:"never"}).error,"bridge_element_disabled");
  window.close();
});
test("fixed extractors scope one-time keys to visible official dialogs", () => {
  const {window, run}=dom('<code>sk-proj_OLD_not_real_0123456789abcdef</code><div role="dialog"><code>sk-proj_NEW_not_real_0123456789abcdef</code></div>',"api-keys");
  assert.deepEqual(run({operation:"extract",kind:"new_key"}).result,["sk-proj_NEW_not_real_0123456789abcdef"]);
  window.document.querySelector('[role="dialog"]').hidden=true;
  assert.deepEqual(run({operation:"extract",kind:"new_key"}).result,[]);
  assert.equal(run({operation:"extract",kind:"tunnels"}).error,"bridge_origin_changed");
  window.close();
});
test("tunnel extraction deduplicates without returning page text", () => {
  const {window,run}=dom('<p>private fixture text</p><code>tunnel_abcdefgh12345678</code><code>tunnel_abcdefgh12345678</code>');
  assert.deepEqual(run({operation:"extract",kind:"tunnels"}).result,["tunnel_abcdefgh12345678"]);
  window.close();
});
test("lookalike origins, unsupported actions and attribute reads fail closed", () => {
  const lookalike=dom('<input value="not exported">',"tunnels","https://platform.openai.com.evil.invalid");
  assert.equal(lookalike.run({steps:[],action:"count"}).error,"bridge_origin_changed"); lookalike.window.close();
  const {window,run}=dom('<input value="not exported">');
  assert.equal(run({steps:[{kind:"css",selector:"input"}],action:"attribute",name:"value"}).error,"bridge_selector_ambiguous");
  assert.equal(run({steps:[],action:"eval",source:"document.cookie"}).error,"bridge_selector_ambiguous"); window.close();
});
function background(tabs=[],windows=[{id:7,incognito:false,focused:true}]) {
  const messages=[], listeners=[],removed=[],updates=[],created=[],duplicated=[];
  const port={postMessage:value=>messages.push(value), onMessage:{addListener:f=>listeners.push(f)},onDisconnect:{addListener:()=>{}}};
  const api={runtime:{connectNative:()=>port,onInstalled:{addListener:()=>{}},onStartup:{addListener:()=>{}}},
    action:{onClicked:{addListener:()=>{}}},alarms:{create:async()=>{},onAlarm:{addListener:()=>{}}},
    windows:{getAll:async()=>windows},tabs:{query:async()=>tabs,get:async id=>{if(id!==42)throw Error();return {id:42,url:"https://platform.openai.com/settings/organization/tunnels?private-fixture=never-forwarded"};},
      create:async value=>{created.push(value);return {id:42};},duplicate:async id=>{duplicated.push(id);return {id:42};},remove:async id=>removed.push(id),update:async(...args)=>updates.push(args)}};
  vm.runInNewContext(fs.readFileSync(path.join(root,"firefox/background.js"),"utf8"),{browser:api,URL,console,setTimeout});
  let next=0;
  return {messages,removed,updates,created,duplicated,async request(command){
    const id=++next;listeners[0]({...command,id});
    for(let i=0;i<100;i++){const response=messages.find(m=>m.id===id);if(response)return response;await new Promise(r=>setTimeout(r,1));}
    throw Error("background fixture timeout");
  }};
}
test("background owns its new tab and cannot mutate original tabs",async()=>{
  const worker=background([{id:9,windowId:7,incognito:false}]);
  assert.equal((await worker.request({operation:"open"})).result,42);
  assert.equal((await worker.request({operation:"navigate",tab:9,url:"https://platform.openai.com/settings/organization/api-keys"})).error,"browser_closed");
  assert.equal((await worker.request({operation:"close",tab:42})).ok,true);
  assert.deepEqual(worker.removed,[42]); assert.equal(worker.updates.length,1);
  assert.equal(worker.updates[0][0],42); assert.deepEqual(worker.duplicated,[9]);
});
test("private windows and ambiguous Platform tabs are rejected",async()=>{
  const privateOnly=background([],[{id:8,incognito:true}]);
  assert.equal((await privateOnly.request({operation:"open"})).error,"browser_account_selection_required");
  assert.equal(privateOnly.created.length,0);
  const container=background([{id:9,windowId:7,incognito:false},{id:10,windowId:7,incognito:false}]);
  assert.equal((await container.request({operation:"open"})).error,"browser_account_selection_required");
  assert.equal(container.created.length,0);
});
test("a sole Firefox container tab is duplicated without selecting another cookie store",async()=>{
  const container=background([{id:9,windowId:7,incognito:false,cookieStoreId:"firefox-container-1"}]);
  assert.equal((await container.request({operation:"open"})).result,42);
  assert.deepEqual(container.duplicated,[9]); assert.equal(container.created.length,0);
});
test("URL reporting strips query and fragment data",async()=>{
  const worker=background(); await worker.request({operation:"open"});
  assert.equal((await worker.request({operation:"url",tab:42})).result,"https://platform.openai.com/settings/organization/tunnels");
});
