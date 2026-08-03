/* InMoov Hand — front-end logic.
 *   MOCK : in-browser demo with fake data + simulated EEG cue stream (file:// or ?mock)
 *   LIVE : talks to the ESP32 REST/WebSocket API (Contract B)  [later firmware layers]
 */
(() => {
  "use strict";
  // MOCK = no ESP32 backend present (file://, ?mock, or a local preview server)
  const MOCK = location.protocol === "file:" ||
               new URLSearchParams(location.search).has("mock") ||
               /^(localhost|127\.|0\.0\.0\.0)/.test(location.hostname);

  // ---- contract constants (mirror CONTRACTS.md) ----
  const LABELS = ["single_blink","double_blink","clinch","bruxism_left","bruxism_right","rest"];
  const LABEL_TEXT = {single_blink:"Single blink",double_blink:"Double blink",clinch:"Clinch",
    bruxism_left:"Bruxism left",bruxism_right:"Bruxism right",rest:"Rest"};
  const BUILTINS = ["open_hand","close_fist","point","pinch","wrist_left","wrist_right","relax"];
  const CHAN = ["Thumb","Index","Middle","Ring","Pinky","Wrist"];
  // Wrist neutral is 40 (not 90). wrist_left/right HOLD current finger angles and
  // only rotate the wrist — see resolveAction(); their wrist endpoints are 180 / 0.
  const ACTION_ANGLES = {
    open_hand:[0,0,0,0,0,40], close_fist:[180,180,180,180,180,40], point:[180,0,180,180,180,40],
    pinch:[130,130,0,0,0,40], wrist_left:[0,0,0,0,0,180], wrist_right:[0,0,0,0,0,0], relax:[20,20,20,20,20,40]
  };
  const humanize = s => s.replace(/_/g," ").replace(/^./,c=>c.toUpperCase());

  // ---- state ----
  const state = {
    status:{battery_pct:87, battery_v:7.92, linkA_connected:true,
      last_label:"", last_action:"", source:"",
      servo_angles:[0,0,0,0,0,40], active_pose:null},
    mappings:{single_blink:"open_hand",double_blink:"pinch",clinch:"close_fist",
      bruxism_left:"wrist_left",bruxism_right:"wrist_right",rest:"relax"},
    poses:[{name:"ok_sign",angles:[120,100,10,10,10,90]}]
  };
  const cueFeed=[];   // recent {label,action} — newest first (dashboard feed)
  const draft=[0,0,0,0,0,90]; let editingPose=null, hand3d=null;

  // ---- user settings + on-device persistence ----
  const settings={firstName:"",lastName:"",deviceName:"",hand:"right",theme:"light"};
  const SKEY="inmoov.v1";
  function persist(){try{localStorage.setItem(SKEY,JSON.stringify({settings,poses:state.poses,mappings:state.mappings}));}catch(e){}}
  function hydrate(){try{const s=JSON.parse(localStorage.getItem(SKEY));if(!s)return;
    Object.assign(settings,s.settings||{});
    if(Array.isArray(s.poses)&&s.poses.length)state.poses=s.poses;
    if(s.mappings)Object.assign(state.mappings,s.mappings);}catch(e){}}

  const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];

  // ---- SVG hand (pose editor live preview) ----
  function handMarkup(a){
    const [t,i,m,r,p,w]=a, wristRot=((90-w)/90)*22;
    const F=[{cx:74,w:18,b:150,l:84},{cx:97,w:18,b:150,l:98},{cx:120,w:18,b:150,l:88},{cx:141,w:15,b:150,l:68}];
    const fa=[i,m,r,p]; let s="";
    F.forEach((f,k)=>{const c=fa[k]/180,vis=f.l*(1-.72*c),tip=f.b-vis,hh=(f.b-tip+14).toFixed(1);
      s+=`<rect class="seg" x="${f.cx-f.w/2}" y="${tip.toFixed(1)}" width="${f.w}" height="${hh}" rx="${f.w/2}"/>`;
      s+=`<circle class="tip" cx="${f.cx}" cy="${(tip+5).toFixed(1)}" r="3.4"/>`;});
    const ct=t/180,tR=-32+64*ct,tL=58*(1-.25*ct),bx=60,by=178;
    s+=`<g transform="rotate(${tR.toFixed(1)} ${bx} ${by})"><rect class="seg" x="${bx-9}" y="${(by-tL).toFixed(1)}" width="18" height="${(tL+12).toFixed(1)}" rx="9"/><circle class="tip" cx="${bx}" cy="${(by-tL+6).toFixed(1)}" r="3.4"/></g>`;
    return `<svg viewBox="0 0 200 232" class="hand"><g transform="rotate(${wristRot.toFixed(1)} 100 190)"><rect class="palm" x="56" y="150" width="90" height="74" rx="24"/>${s}<rect class="wrist" x="74" y="216" width="52" height="16" rx="8"/></g></svg>`;
  }
  const drawSvg=(el,a)=>{if(el) el.innerHTML=handMarkup(a);};

  // ---- home dashboard ----
  function batteryLevel(p){ return p<=10?"crit":p<=25?"low":"ok"; }
  function renderMini(){
    const s=state.status, p=s.battery_pct;
    // battery chip: text + colour band + icon fill width
    $("#battText").textContent=p+"%";
    const bc=$("#battChip"); bc.dataset.lvl=batteryLevel(p);
    const lvl=bc.querySelector(".lvl"); if(lvl) lvl.style.transform=`scaleX(${Math.max(.06,p/100).toFixed(2)})`;
    bc.title=`Battery ${p}%`+(s.battery_v?` · ${(+s.battery_v).toFixed(2)} V`:"");
    // EEG link chip
    const ec=$("#eegChip"); ec.dataset.up=s.linkA_connected?"1":"0";
    $("#eegText").textContent=s.linkA_connected?"EEG":"No signal";
    // fail-safe banner (link lost -> holding position)
    $("#failsafe").hidden=!!s.linkA_connected;
  }
  function renderHud(){
    const s=state.status;
    $("#hudCue").textContent=s.last_label?humanize(s.last_label):"—";
    $("#hudAction").textContent=s.last_action?humanize(s.last_action):"Ready";
    const src=$("#hudSrc");
    if(s.source){ src.hidden=false; src.dataset.src=s.source; src.textContent=s.source==="cue"?"Auto":"Manual"; }
    else src.hidden=true;
    $("#hudFeed").innerHTML=cueFeed.slice(0,4).map(c=>
      `<span class="fc">${humanize(c.label)} → ${humanize(c.action)}</span>`).join("");
  }
  function pushFeed(label,action){
    if(!label) return;
    cueFeed.unshift({label,action:action||"—"});
    if(cueFeed.length>8) cueFeed.length=8;
  }
  function renderDashboard(){ renderMini(); renderHud(); }
  function setHomeSub(txt){ $("#homeSub").textContent=txt; }
  function updateGreeting(){ const el=$("#homeName"); if(el) el.textContent=(settings.firstName||"").trim()||"User"; }

  // ---- settings ----
  function applyTheme(){ document.documentElement.setAttribute("data-theme",settings.theme);
    const t=$("#darkToggle"); if(t) t.setAttribute("aria-checked",settings.theme==="dark"?"true":"false"); }
  function renderSettings(){
    $("#setFirst").value=settings.firstName||""; $("#setLast").value=settings.lastName||"";
    $("#setDevice").value=settings.deviceName||"";
    $$("#setHand button").forEach(b=>b.classList.toggle("active",b.dataset.hand===settings.hand));
    applyTheme();
  }
  function saveProfile(){
    settings.firstName=$("#setFirst").value.trim(); settings.lastName=$("#setLast").value.trim();
    settings.deviceName=$("#setDevice").value.trim();
    persist(); updateGreeting(); toast("Profile saved");
  }
  // left/right hand: mirror the 3D twin so it matches the user's physical hand
  function applyHandMirror(){ if(hand3d && hand3d.setMirror) hand3d.setMirror(settings.hand==="left"); }
  function setHand(h){ settings.hand=h; applyHandMirror(); }

  // ---- mappings ----
  function actionOptions(sel){
    const o=(v)=>`<option value="${v}"${v===sel?" selected":""}>${v.replace(/_/g," ")}</option>`;
    return `<optgroup label="Built-in">${BUILTINS.map(o).join("")}</optgroup>`+
      (state.poses.length?`<optgroup label="Saved poses">${state.poses.map(p=>o(p.name)).join("")}</optgroup>`:"");
  }
  function renderMappings(){
    $("#mapRows").innerHTML=LABELS.map(l=>`<tr><td><div class="cue-name">${LABEL_TEXT[l]}<small>${l}</small></div></td><td><select data-label="${l}">${actionOptions(state.mappings[l])}</select></td></tr>`).join("");
    $$("#mapRows select").forEach(s=>s.onchange=()=>{state.mappings[s.dataset.label]=s.value;persist();});
  }

  // ---- poses ----
  const PRESETS=["open_hand","close_fist","point","pinch"];   // smart starting points for the editor

  function renderPoseList(){
    const host=$("#poseList");
    const cards=state.poses.map(p=>{
      const active=state.status.active_pose===p.name;
      return `<div class="pose-card${active?" active":""}" data-name="${p.name}">
        <span class="del" data-del="${p.name}" title="Delete">&times;</span>
        <div class="thumb">${handMarkup(p.angles)}</div>
        <div class="pose-name">${humanize(p.name)}</div>
        <div class="pose-foot">${active?'<span class="tag">Active</span>':''}<span class="edit" data-edit="${p.name}">Edit</span></div>
      </div>`;}).join("");
    const empty=`<div class="pose-empty">No saved poses yet — shape one below.</div>`;
    const add=`<div class="pose-card add" id="addPose"><span class="plus">+</span><span>New pose</span></div>`;
    host.innerHTML=(state.poses.length?cards:empty)+add;

    $$(".pose-card[data-name]",host).forEach(card=>card.onclick=(e)=>{
      if(e.target.closest(".del")||e.target.closest(".edit"))return; applyPose(card.dataset.name);});
    $$("[data-edit]",host).forEach(b=>b.onclick=(e)=>{e.stopPropagation();const p=state.poses.find(x=>x.name===b.dataset.edit);if(p)loadPose(p);});
    $$("[data-del]",host).forEach(b=>b.onclick=(e)=>{e.stopPropagation();deletePose(b.dataset.del);});
    const addBtn=$("#addPose",host); if(addBtn) addBtn.onclick=()=>{newPose();$("#poseName").focus();};
  }
  function renderPresets(){
    const host=$("#presets"); if(!host)return;
    host.innerHTML=PRESETS.map(n=>`<button class="preset" data-preset="${n}">${humanize(n)}</button>`).join("");
    $$(".preset",host).forEach(b=>b.onclick=()=>seedPreset(b.dataset.preset));
  }
  function seedPreset(name){const a=ACTION_ANGLES[name];if(!a)return;
    for(let i=0;i<6;i++)draft[i]=a[i]; renderSliders(); toast(`Loaded ${humanize(name)}`);}
  function setEditorTitle(){const el=$("#editorTitle");if(el)el.textContent=editingPose?`Editing “${editingPose}”`:"New pose";}
  function renderSliders(){
    $("#sliders").innerHTML=CHAN.map((nm,i)=>`<div class="slider"><label>${nm}</label><input type="range" min="0" max="180" value="${draft[i]}" data-ch="${i}"><span class="val" data-val="${i}">${draft[i]}&deg;</span></div>`).join("");
    $$("#sliders input").forEach(inp=>inp.oninput=()=>{const c=+inp.dataset.ch;draft[c]=+inp.value;
      $(`[data-val="${c}"]`).innerHTML=draft[c]+"&deg;"; drawSvg($("#handPose"),draft); api.servo(c,draft[c]);});
    drawSvg($("#handPose"),draft);
  }

  function resolveAction(a){
    // wrist actions hold the live finger angles and only rotate the wrist
    if(a==="wrist_left"||a==="wrist_right"){const cur=state.status.servo_angles.slice();cur[5]=a==="wrist_left"?180:0;return cur;}
    if(ACTION_ANGLES[a])return ACTION_ANGLES[a].slice();
    const p=state.poses.find(x=>x.name===a);return p?p.angles.slice():null;}
  function driveHand(angles,label){ state.status.servo_angles=angles.slice(); if(hand3d) hand3d.setPose(angles); if(label) setHomeSub(label); }

  function markManual(action){ state.status.source="manual"; state.status.last_action=action||""; renderDashboard(); }
  function applyPose(name){const p=state.poses.find(x=>x.name===name);if(!p)return;
    state.status.active_pose=name; driveHand(p.angles,humanize(name)); api.applyPose(name); markManual(name); renderPoseList(); toast(`Applied “${name}”`);}
  function deletePose(name){state.poses=state.poses.filter(p=>p.name!==name);if(editingPose===name)editingPose=null;
    // rebind any mapping that pointed at the deleted pose so its cue still does something (mirrors firmware)
    Object.keys(state.mappings).forEach(l=>{if(state.mappings[l]===name)state.mappings[l]="relax";});
    api.deletePose(name); persist(); renderPoseList(); renderMappings(); setEditorTitle(); toast(`Deleted “${name}”`);}
  function loadPose(p){editingPose=p.name;for(let i=0;i<6;i++)draft[i]=p.angles[i];$("#poseName").value=p.name;
    renderSliders(); setEditorTitle(); $("#editorCard").scrollIntoView({behavior:"smooth",block:"start"}); toast(`Editing “${p.name}”`);}
  function savePose(){const name=$("#poseName").value.trim();if(!name){toast("Name the pose first");return;}
    const ex=state.poses.find(p=>p.name===name);if(ex)ex.angles=draft.slice();else state.poses.push({name,angles:draft.slice()});
    editingPose=name; api.savePose(name,draft.slice()); persist(); renderPoseList(); renderMappings(); setEditorTitle(); toast(`Saved “${name}”`);}
  function newPose(){editingPose=null;[0,0,0,0,0,90].forEach((v,i)=>draft[i]=v);$("#poseName").value="";renderSliders();setEditorTitle();}
  function relax(){state.status.active_pose=null; driveHand(ACTION_ANGLES.relax,"Relaxed"); api.relax(); markManual("relax"); toast("Relaxed / opened");}
  // Home the hand — open fingers + wrist neutral (40°). Fired once when the app connects.
  function resetHand(){state.status.active_pose=null; driveHand(ACTION_ANGLES.open_hand.slice(),"Hand ready"); markManual("open_hand"); api.applyPose("open_hand");}

  // ---- API layer (no-op in MOCK) ----
  const api=MOCK?{servo(){},applyPose(){},savePose(){},deletePose(){},relax(){},saveMappings(){}}:{
    servo:(channel,angle)=>post("/api/servo",{channel,angle}),
    applyPose:name=>post("/api/pose/apply",{name}),
    savePose:(name,angles)=>post("/api/poses",{name,angles}),
    deletePose:name=>fetch("/api/poses/"+encodeURIComponent(name),{method:"DELETE"}),
    relax:()=>post("/api/relax",{}), saveMappings:()=>post("/api/mappings",state.mappings)
  };
  const post=(u,b)=>fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)}).catch(()=>{});

  // ---- mock simulator ----
  function startSim(){
    setInterval(()=>{if(document.hidden)return;
      if(Math.random()<.35) state.status.battery_pct=Math.max(3,state.status.battery_pct-1);
      state.status.battery_v=+(6.6+state.status.battery_pct/100*1.7).toFixed(2); renderMini();},4500);
    setInterval(()=>{if(document.hidden)return;
      // ~1 in 7 ticks: simulate an EEG dropout so the fail-safe banner is visible
      if(Math.random()<.14){ state.status.linkA_connected=false; renderMini(); return; }
      receiveCue(LABELS[Math.floor(Math.random()*LABELS.length)]);},5200);
  }
  function receiveCue(lbl){
    const action=state.mappings[lbl], angles=resolveAction(action);
    state.status.last_label=lbl; state.status.last_action=action||""; state.status.source="cue";
    state.status.linkA_connected=true;
    state.status.active_pose=state.poses.some(p=>p.name===action)?action:null;
    pushFeed(lbl,action);
    if(angles) driveHand(angles, humanize(action));
    renderDashboard();
  }

  // ---- nav + toast ----
  function switchTab(name){
    $$(".screen").forEach(s=>s.classList.toggle("active",s.id===name));
    $$(".navbtn").forEach(b=>b.classList.toggle("active",b.dataset.tab===name));
  }
  let toastT=null;
  function toast(msg){const el=$("#toast");el.textContent=msg;el.hidden=false;clearTimeout(toastT);toastT=setTimeout(()=>el.hidden=true,1600);}

  // ---- init ----
  function init(){
    hydrate();
    $$(".navbtn").forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
    $("#saveMap").onclick=()=>{api.saveMappings();persist();toast("Mappings saved");};
    $("#savePose").onclick=savePose;
    $("#newPose").onclick=newPose;
    $("#relaxBtn").onclick=relax;
    $("#homeRelax").onclick=relax;
    $("#applyPose").onclick=()=>{const name=$("#poseName").value.trim();state.status.active_pose=name||null;
      driveHand(draft.slice(),name?humanize(name):"Custom pose"); markManual(name||"custom"); toast(name?`Applied “${name}”`:"Applied to hand");};

    // settings
    $("#saveProfile").onclick=saveProfile;
    $("#darkToggle").onclick=()=>{settings.theme=settings.theme==="dark"?"light":"dark";applyTheme();persist();};
    $$("#setHand button").forEach(b=>b.onclick=()=>{setHand(b.dataset.hand);
      $$("#setHand button").forEach(x=>x.classList.toggle("active",x===b));persist();});
    $("#resetData").onclick=()=>{if(confirm("Reset all saved data on this device? This clears your profile, poses and mappings.")){localStorage.removeItem(SKEY);location.reload();}};

    renderDashboard(); renderMappings(); renderPresets(); renderPoseList(); renderSliders(); setEditorTitle();
    renderSettings(); updateGreeting();

    // 3D twin is best-effort: a WebGL failure must NOT stop the dashboard,
    // cue stream, or live telemetry from working.
    if(window.Hand3D && window.THREE){
      try{
        hand3d=window.Hand3D($("#stage"));
        applyHandMirror();
        hand3d.setPose(state.status.servo_angles);
        setTimeout(()=>{try{hand3d.wave();}catch(e){}},350);
      }catch(e){ hand3d=null; console.warn("3D hand unavailable:",e&&e.message); }
    }
    if(MOCK){$("#mockbanner").hidden=false; startSim();}
    else connectLive();
  }

  // ---- LIVE: REST hydrate + WebSocket telemetry (Contract B) ----
  function connectLive(){
    // 1) pull the authoritative snapshot so the UI matches the device on load
    fetch("/api/state").then(r=>r.json()).then(d=>{
      if(d.status) Object.assign(state.status, d.status);
      if(d.mappings) Object.assign(state.mappings, d.mappings);
      if(Array.isArray(d.poses)) state.poses=d.poses;
      renderDashboard(); renderMappings(); renderPoseList();
      if(state.status.servo_angles) driveHand(state.status.servo_angles);
      resetHand();   // reset to home (open + wrist neutral) whenever the app connects
    }).catch(()=>{});
    openWs();
  }
  function applyStatus(s){
    const prevLabel=state.status.last_label;
    Object.assign(state.status, s);
    // a new cue arrived -> log it in the feed
    if(s.last_label && s.last_label!==prevLabel && s.source==="cue")
      pushFeed(s.last_label, s.last_action);
    if(s.servo_angles) driveHand(s.servo_angles);
    renderDashboard();
  }
  function openWs(){
    let ws, retry=0;
    const url=(location.protocol==="https:"?"wss://":"ws://")+location.host+"/ws";
    (function conn(){
      try{ ws=new WebSocket(url); }catch(e){ return schedule(); }
      ws.onmessage=(ev)=>{ try{const m=JSON.parse(ev.data); if(m.type==="status") applyStatus(m);}catch(e){} };
      ws.onopen=()=>{ retry=0; };
      ws.onclose=schedule; ws.onerror=()=>{ try{ws.close();}catch(e){} };
      function schedule(){ retry=Math.min(retry+1,6); setTimeout(conn, 500*retry); }
    })();
  }
  document.addEventListener("DOMContentLoaded",init);
})();
