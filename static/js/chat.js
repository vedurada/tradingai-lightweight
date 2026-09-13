/* TradingAI Live Chat — every page, anon/login, live + alerts (VM-light: polling 4s chat / 15s alerts, nginx 10s cache) */
(() => {
  const API = (p) => p; // same-origin /api via nginx -> 127.0.0.1:8000 (10s cache)
  const CH_KEY = "ta_chat_user";
  const CH_NOTIFY = "ta_chat_notify";
  const $ = (s, r=document) => r.querySelector(s);
  let username = (localStorage.getItem(CH_KEY) || "").trim() || "Anonymous" + Math.floor(100+Math.random()*900);
  let channel = "global";
  let lastId = 0;
  let lastAlertId = 0;
  let muted = localStorage.getItem("ta_chat_muted")==="1";
  let unread = 0;
  let open = false;
  let pollChat = null, pollAlert = null;
  let bc = null;
  try{ bc = new BroadcastChannel("ta_chat"); bc.onmessage = (e)=>{ if(e.data && e.data.type==="msg") prepend([e.data.msg], true); if(e.data && e.data.type==="alert") onAlert(e.data.msg,true); }; }catch(e){}

  function ensureUI(){
    if($("#ta-chat-bubble")) return;
    const link = document.createElement("link");
    link.rel = "stylesheet"; link.href = "/assets/css/chat.css";
    document.head.appendChild(link);
    const bubble = document.createElement("div");
    bubble.id = "ta-chat-bubble";
    bubble.innerHTML = `<span class="dot"></span> Live Chat <span class="badge" id="ta-chat-badge">0</span> <span style="opacity:.8;font-weight:400" id="ta-chat-online"></span>`;
    bubble.title = "Chat with traders — alerts in real time";
    document.body.appendChild(bubble);
    const panel = document.createElement("div");
    panel.id = "ta-chat-panel";
    panel.innerHTML = `
      <div id="ta-chat-head"><div><b>💬 TradingAI Live</b><div class="sub" id="ta-chat-sub">Global • share knowledge, ask questions</div></div><div style="display:flex;gap:6px"><button id="ta-chat-mute" style="background:#1e293b;color:#fff;border:1px solid #334155;border-radius:8px;padding:6px 8px;font:600 11px system-ui;cursor:pointer">${muted?"🔕":"🔔"}</button><button id="ta-chat-close" style="background:transparent;color:#fff;border:1px solid #334155;border-radius:8px;padding:6px 8px;cursor:pointer">✕</button></div></div>
      <div id="ta-chat-tabs">
        <button data-ch="global" class="active">Global</button>
        <button data-ch="nifty">NIFTY</button>
        <button data-ch="alerts">Alerts 🔔</button>
      </div>
      <div id="ta-chat-log"></div>
      <div id="ta-chat-foot">
        <div id="ta-chat-login">
          <input id="ta-chat-user" maxlength="20" placeholder="Your name" value="${escAttr(username)}" />
          <button id="ta-chat-save">Save</button>
          <small id="ta-chat-who" style="white-space:nowrap"></small>
        </div>
        <form id="ta-chat-form">
          <input id="ta-chat-input" maxlength="300" placeholder="Message — be helpful, no spam" autocomplete="off" />
          <button type="submit">Send</button>
        </form>
        <small>Enter to send • 8/min • alerts auto-post here</small>
      </div>`;
    document.body.appendChild(panel);
    const toast = document.createElement("div");
    toast.id = "ta-chat-toast"; document.body.appendChild(toast);

    $("#ta-chat-bubble").addEventListener("click", ()=> toggle(true));
    $("#ta-chat-close").addEventListener("click", ()=> toggle(false));
    $("#ta-chat-mute").addEventListener("click", ()=>{
      muted=!muted; localStorage.setItem("ta_chat_muted", muted?"1":"0");
      $("#ta-chat-mute").textContent = muted?"🔕":"🔔";
    });
    panel.querySelectorAll("#ta-chat-tabs button").forEach(b=>{
      b.addEventListener("click", ()=>{
        panel.querySelectorAll("#ta-chat-tabs button").forEach(x=>x.classList.remove("active"));
        b.classList.add("active");
        channel = b.dataset.ch;
        $("#ta-chat-sub").textContent = channel==="global" ? "Global • share knowledge" : channel==="alerts" ? "Alerts • AI trades, news, closes" : channel.toUpperCase()+" • per-symbol chat";
        lastId = 0; $("#ta-chat-log").innerHTML = "";
        fetchChat(true);
        if(channel==="alerts") fetchAlerts(true);
      });
    });
    $("#ta-chat-save").addEventListener("click", saveUser);
    $("#ta-chat-user").addEventListener("keydown", e=>{ if(e.key==="Enter"){ e.preventDefault(); saveUser(); }});
    $("#ta-chat-form").addEventListener("submit", send);
    updateWho();
  }

  function esc(s){ return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;","&gt;":"&gt;"}[c])); }
  function escAttr(s){ return esc(s).replace(/"/g,"&quot;"); }
  function fmtTime(iso){ try{ const d=new Date(iso); return d.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'}); }catch(e){ return ""; } }

  function updateWho(){ const el=$("#ta-chat-who"); if(el) el.textContent = "You: "+username; const b=$("#ta-chat-badge"); if(b){ b.style.display=unread>0?"inline-block":"none"; b.textContent=unread>99?"99+":unread; } }

  function saveUser(){
    const v = ($("#ta-chat-user").value||"").trim().slice(0,20);
    if(v) { username=v; localStorage.setItem(CH_KEY, v); updateWho(); toast("Saved as "+v); }
  }

  function toggle(force){
    ensureUI();
    const p=$("#ta-chat-panel");
    open = typeof force==="boolean" ? force : !p.classList.contains("open");
    p.classList.toggle("open", open);
    if(open){ unread=0; updateWho(); fetchChat(true); fetchAlerts(true); startPolling(); $("#ta-chat-input").focus(); }
    else stopPolling();
  }

  function renderMsg(m){
    const me = m.username===username;
    const isAlert = m.kind==="alert";
    const cls = isAlert ? "alert" : m.kind==="system" ? "system" : me ? "me" : "";
    return `<div class="ta-msg ${cls}"><div class="meta">${esc(m.username)} <span>${fmtTime(m.created_at)} ${isAlert?"• ALERT":""}</span></div><div class="text">${esc(m.text)}</div></div>`;
  }

  function prepend(list, fromBC){
    if(!list || !list.length) return;
    const log=$("#ta-chat-log");
    if(!log) return;
    // filter by channel
    const filtered = list.filter(m=> (m.channel||"global")===channel || channel==="global" && (m.channel==="global"|| !m.channel) || channel==="alerts" && m.kind==="alert");
    if(!filtered.length && channel!=="alerts") {
      // for global, show only global; for alerts, show only alerts
      if(channel==="global") {
        const g = list.filter(m=> (m.channel||"global")==="global");
        if(!g.length) return;
        g.forEach(m=> log.insertAdjacentHTML("beforeend", renderMsg(m)));
      }
      return;
    }
    const toShow = channel==="alerts" ? list.filter(m=> m.kind==="alert") : filtered;
    toShow.forEach(m=> log.insertAdjacentHTML("beforeend", renderMsg(m)));
    log.scrollTop = log.scrollHeight;
    if(!open){
      unread += toShow.length;
      updateWho();
      if(toShow.some(m=> m.kind==="alert") && !muted) ping();
    } else if(toShow.some(m=> m.kind==="alert") && !muted) {
      // subtle ping when open too
      try{ new Audio("data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRyAgAAAAA=").play().catch(()=>{}); }catch(e){}
    }
    // dedup via lastId handled by caller
  }

  async function fetchChat(force){
    try{
      const url = API("/api/chat/messages?channel="+encodeURIComponent(channel)+"&since="+lastId+"&limit=30");
      const r = await fetch(url, {cache:"no-store"});
      if(!r.ok) return;
      const arr = await r.json();
      if(!Array.isArray(arr) || !arr.length) return;
      lastId = Math.max(lastId, ...arr.map(x=>x.id));
      prepend(arr);
      // broadcast to other tabs
      if(bc && !force) arr.forEach(m=> bc.postMessage({type:"msg", msg:m}));
    }catch(e){}
  }

  async function fetchAlerts(force){
    try{
      const r = await fetch(API("/api/chat/alerts?limit=10"), {cache:"no-store"});
      if(!r.ok) return;
      const arr = await r.json();
      if(!Array.isArray(arr) || !arr.length) return;
      const news = arr.filter(m=> m.id > lastAlertId);
      if(!news.length) return;
      lastAlertId = Math.max(lastAlertId, ...arr.map(x=>x.id));
      // show in current channel if alerts or global
      if(channel==="alerts" || channel==="global") prepend(news);
      // popup for newest alert
      const latest = news[news.length-1];
      if(latest && !muted) onAlert(latest, false);
      if(bc) news.forEach(m=> bc.postMessage({type:"alert", msg:m}));
    }catch(e){}
  }

  function onAlert(m, fromBC){
    if(muted) return;
    const txt = m.text.length>90 ? m.text.slice(0,90)+"…" : m.text;
    toast("🔔 "+txt, 6000);
    try{
      if("Notification" in window && Notification.permission==="granted") new Notification("TradingAI Alert", {body: txt});
      else if("Notification" in window && Notification.permission!=="denied") Notification.requestPermission();
    }catch(e){}
    // beep via WebAudio
    try{
      const ctx = new (window.AudioContext||window.webkitAudioContext)();
      const o=ctx.createOscillator(), g=ctx.createGain();
      o.type="sine"; o.frequency.value=880; g.gain.value=0.08;
      o.connect(g); g.connect(ctx.destination); o.start(); setTimeout(()=>{o.stop(); ctx.close();}, 180);
    }catch(e){}
    if(!fromBC && bc) bc.postMessage({type:"alert", msg:m});
  }

  function toast(msg, ms=2500){
    const t=$("#ta-chat-toast"); if(!t) return;
    t.textContent=msg; t.classList.add("show");
    clearTimeout(t._to); t._to=setTimeout(()=> t.classList.remove("show"), ms);
  }
  function ping(){ toast("New message"); }

  async function send(e){
    e.preventDefault();
    const inp=$("#ta-chat-input");
    const text=(inp.value||"").trim();
    if(!text) return;
    if(text.length>300) { toast("Max 300 chars"); return; }
    inp.value="";
    // optimistic
    const tmp={id:Date.now(), channel, username, text, kind:"user", created_at:new Date().toISOString()};
    prepend([tmp]);
    try{
      const r=await fetch(API("/api/chat/messages"), {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({channel, username, text, kind:"user"})});
      if(r.status===429){ toast("Slow down — 8/min"); return; }
      if(!r.ok){ toast("Send failed"); return; }
      const saved=await r.json();
      lastId=Math.max(lastId, saved.id);
      if(bc) bc.postMessage({type:"msg", msg:saved});
    }catch(err){ toast("Offline — will retry"); }
  }

  function startPolling(){
    stopPolling();
    pollChat=setInterval(()=> fetchChat(false), 4000);
    pollAlert=setInterval(()=> fetchAlerts(false), 15000);
  }
  function stopPolling(){ if(pollChat) clearInterval(pollChat); if(pollAlert) clearInterval(pollAlert); pollChat=pollAlert=null; }

  // auto-init on every page (after DOM)
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded", ()=>{ ensureUI(); fetchChat(true); fetchAlerts(true); setTimeout(startPolling, 2000); });
  else { ensureUI(); fetchChat(true); fetchAlerts(true); setTimeout(startPolling, 2000); }

  // expose for debugging
  window.TAChat = {toggle, fetchChat, fetchAlerts};
})();
