"""The single-page remote UI, embedded so it needs no data files or internet."""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Sound xR OSC Bridge</title>
<style>
  :root{
    --bg:#14161a; --panel:#1c2027; --line:#2c323c; --text:#e8ebf0; --dim:#98a1b0;
    --accent:#4aa3ff; --ok:#3ecf8e; --warn:#ffb454; --bad:#ff6b6b; --radius:10px;
  }
  @media (prefers-color-scheme: light){
    :root{ --bg:#f4f6f9; --panel:#fff; --line:#dde3ec; --text:#151922; --dim:#5d6774; }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
       font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       -webkit-text-size-adjust:100%}
  header{position:sticky;top:0;z-index:5;background:var(--panel);
         border-bottom:1px solid var(--line);padding:10px 14px;
         display:flex;gap:12px;align-items:center;flex-wrap:wrap}
  h1{font-size:16px;margin:0;font-weight:650}
  .ver{color:var(--dim);font-size:12px}
  .dot{width:10px;height:10px;border-radius:50%;background:var(--bad);flex:none}
  .dot.on{background:var(--ok)}
  .counts{color:var(--dim);font-size:13px;margin-left:auto;font-variant-numeric:tabular-nums}
  button{font:inherit;color:var(--text);background:var(--panel);border:1px solid var(--line);
         border-radius:var(--radius);padding:9px 14px;cursor:pointer;min-height:40px}
  button:active{transform:translateY(1px)}
  button.primary{background:var(--accent);border-color:var(--accent);color:#06121f;font-weight:600}
  button.danger{border-color:var(--bad);color:var(--bad)}
  button.small{padding:5px 9px;min-height:32px;font-size:13px}
  nav{display:flex;gap:6px;padding:10px 14px 0;flex-wrap:wrap}
  nav button{border-radius:999px}
  nav button.sel{background:var(--accent);border-color:var(--accent);color:#06121f;font-weight:600}
  main{padding:12px 14px 40px;max-width:1100px;margin:0 auto}
  section{display:none} section.show{display:block}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
        padding:12px;margin-bottom:12px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{color:var(--dim);text-align:left;font-weight:600;padding:6px 8px;
     border-bottom:1px solid var(--line);white-space:nowrap}
  td{padding:8px;border-bottom:1px solid var(--line);vertical-align:middle}
  tr.tap{cursor:pointer} tr.tap:active{background:var(--line)}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
  label{display:block;font-size:12px;color:var(--dim);margin-bottom:3px}
  input,select{font:inherit;width:100%;padding:9px 10px;border-radius:8px;
               border:1px solid var(--line);background:var(--bg);color:var(--text);min-height:40px}
  input[type=checkbox]{width:22px;height:22px;min-height:0;vertical-align:middle}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .leg{border:1px solid var(--line);border-radius:var(--radius);padding:10px;margin-top:10px}
  .leg h4{margin:0 0 8px;font-size:14px;font-weight:600}
  .tag{font-size:11px;padding:2px 7px;border-radius:999px;border:1px solid var(--line);color:var(--dim)}
  .tag.yosc{border-color:var(--accent);color:var(--accent)}
  .tag.off{border-color:var(--warn);color:var(--warn)}
  pre{margin:0;white-space:pre-wrap;word-break:break-word;font-size:12px;color:var(--dim);
      max-height:240px;overflow:auto}
  .muted{color:var(--dim);font-size:13px}
</style>
</head>
<body>
<header>
  <div class="dot" id="dot"></div>
  <h1>Sound xR OSC Bridge</h1>
  <span class="ver" id="ver"></span>
  <button class="primary" id="run" onclick="toggleRun()">Start</button>
  <span class="counts" id="counts"></span>
</header>

<nav>
  <button class="sel" data-tab="in" onclick="tab('in')">Incoming</button>
  <button data-tab="map" onclick="tab('map')">Mappings</button>
  <button data-tab="set" onclick="tab('set')">Setup</button>
  <button data-tab="log" onclick="tab('log')">Log</button>
</nav>

<main>
  <section id="s-in" class="show">
    <div class="card">
      <div class="row" style="margin-bottom:8px">
        <strong>Incoming OSC</strong>
        <span class="muted">tap a row to map it</span>
        <button class="small" style="margin-left:auto" onclick="cmd('clear_discovery')">Clear</button>
      </div>
      <div style="overflow-x:auto"><table id="disc"></table></div>
    </div>
  </section>

  <section id="s-map">
    <div id="routes"></div>
    <p class="muted">Mappings are edited live. Use Setup &rarr; Save project to keep them.</p>
  </section>

  <section id="s-set"><div id="setup"></div></section>

  <section id="s-log"><div class="card"><pre id="log"></pre></div></section>
</main>

<script>
var S = null, shown = 'in', drawnRev = -1;

function tab(name){
  shown = name;
  document.querySelectorAll('nav button').forEach(function(b){
    b.classList.toggle('sel', b.dataset.tab === name);
  });
  document.querySelectorAll('section').forEach(function(s){
    s.classList.toggle('show', s.id === 's-' + name);
  });
  drawnRev = -1; draw();
}

function esc(s){ return String(s).replace(/[&<>"]/g, function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

function api(path, body){
  return fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json'},
                             body: JSON.stringify(body)} : undefined)
    .then(function(r){ return r.json(); });
}
function cmd(name, data){
  var payload = Object.assign({cmd:name}, data || {});
  return api('/api/command', payload).then(function(res){
    if(res && res.error){ alert(res.error); }
    if(res && res.warning){ alert(res.warning); }
    return poll();
  });
}
function toggleRun(){ cmd(S && S.running ? 'stop' : 'start'); }

function poll(){
  return api('/api/state').then(function(s){ S = s; draw(); })
    .catch(function(){ document.getElementById('counts').textContent = 'disconnected'; });
}

function draw(){
  if(!S) return;
  document.getElementById('ver').textContent = 'v' + S.version;
  document.getElementById('dot').className = 'dot' + (S.running ? ' on' : '');
  document.getElementById('run').textContent = S.running ? 'Stop' : 'Start';
  var skipped = Object.keys(S.counters.skipped || {}).filter(function(k){
    return S.counters.skipped[k] > 0; });
  document.getElementById('counts').textContent =
    S.counters['in'] + ' in / ' + S.counters.out + ' out' +
    (skipped.length ? '  ⚠ ' + skipped.join(', ') + ' output off' : '');

  if(shown === 'in') drawDiscovery();
  if(shown === 'log') document.getElementById('log').textContent = S.log.join('\n');
  if(shown === 'set' && S.revision !== drawnRev) drawSetup();
  if(shown === 'map' && S.revision !== drawnRev && !editing()) drawRoutes();
  drawnRev = S.revision;
}

function editing(){
  var a = document.activeElement;
  return a && (a.tagName === 'INPUT' || a.tagName === 'SELECT');
}

function drawDiscovery(){
  var rows = ['<tr><th>Address</th><th>Types</th><th>Hz</th><th>Count</th>' +
              '<th>Last values</th><th></th></tr>'];
  S.discovery.forEach(function(d){
    rows.push('<tr class="tap" onclick="cmd(\'add_route\',{address:' +
      JSON.stringify(d.address).replace(/"/g, '&quot;') + '}).then(function(){tab(\'map\')})">' +
      '<td class="mono">' + esc(d.address) + '</td>' +
      '<td class="mono">' + esc(d.types) + '</td>' +
      '<td>' + d.rate + '</td><td>' + d.count + '</td>' +
      '<td class="mono">' + esc(d.last.join('  ')) + '</td>' +
      '<td><button class="small">Map</button></td></tr>');
  });
  if(S.discovery.length === 0)
    rows.push('<tr><td colspan="6" class="muted">Nothing received yet. ' +
              'Press Start, and check the input port in Setup.</td></tr>');
  document.getElementById('disc').innerHTML = rows.join('');
}

function num(v){ return (Math.round(v * 10000) / 10000); }

function drawRoutes(){
  var out = [];
  S.routes.forEach(function(r){
    var h = ['<div class="card">'];
    h.push('<div class="row">' +
      '<input style="flex:2;min-width:180px" class="mono" value="' + esc(r.source) +
        '" onchange="setRoute(' + r.index + ',{source:this.value})">' +
      '<label style="margin:0">arg<input type="number" style="width:70px" value="' +
        r.arg_index + '" onchange="setRoute(' + r.index + ',{arg_index:+this.value})"></label>' +
      '<label style="margin:0">on<input type="checkbox" ' + (r.enabled ? 'checked' : '') +
        ' onchange="setRoute(' + r.index + ',{enabled:this.checked})"></label>' +
      '<button class="small" onclick="cmd(\'add_leg\',{route:' + r.index + '})">+ leg</button>' +
      '<button class="small danger" onclick="cmd(\'del_route\',{route:' + r.index +
        '})">delete</button></div>');
    r.legs.forEach(function(l){ h.push(leg(r, l)); });
    h.push('</div>');
    out.push(h.join(''));
  });
  if(!S.routes.length)
    out.push('<div class="card muted">No mappings yet. Open Incoming and tap an address.</div>');
  document.getElementById('routes').innerHTML = out.join('');
}

function leg(r, l){
  var dest = S.destinations[l.protocol] || {};
  var offTag = dest.enabled ? '' : '<span class="tag off">output off</span>';
  var opts = S.targets.map(function(t){
    return '<option value="' + t.id + '"' + (t.id === l.target_id ? ' selected' : '') + '>' +
           esc(t.group + ' / ' + t.label) + '</option>'; }).join('');
  var args = l.args.map(function(a){
    return '<option' + (a === l.arg ? ' selected' : '') + '>' + esc(a) + '</option>'; }).join('');
  var curves = ['linear','exponential','logarithmic','scurve','breakpoints'].map(function(c){
    return '<option' + (c === l.curve ? ' selected' : '') + '>' + c + '</option>'; }).join('');
  var idx = l.index_specs.map(function(spec){
    return '<div><label>' + esc(spec.label) + '</label><input type="number" min="' + spec.min +
      '" max="' + spec.max + '" value="' + (l.indices[spec.name]) +
      '" onchange="setLeg(' + r.index + ',' + l.index + ',{indices:{' +
      JSON.stringify(spec.name) + ':+this.value}})"></div>'; }).join('');
  var S_ = function(fields){ return 'setLeg(' + r.index + ',' + l.index + ',' + fields + ')'; };
  return '<div class="leg">' +
    '<h4>' + esc(l.target_label) + ' · ' + esc(l.arg) +
      ' <span class="tag ' + (l.protocol === 'yosc' ? 'yosc' : '') + '">' + l.protocol +
      '</span> ' + offTag + '</h4>' +
    '<div class="mono muted" style="margin-bottom:8px">' + esc(l.address) + '</div>' +
    '<div class="grid">' +
      '<div><label>Sound xR parameter</label><select onchange="' +
        S_('{target_id:this.value}') + '">' + opts + '</select></div>' +
      '<div><label>Argument</label><select onchange="' + S_('{arg:this.value}') + '">' +
        args + '</select></div>' + idx +
      '<div><label>Source argument (-1 = route)</label><input type="number" value="' +
        (l.source_arg === null ? -1 : l.source_arg) + '" onchange="' +
        S_('{source_arg:+this.value}') + '"></div>' +
      '<div><label>Input min</label><input type="number" step="any" value="' + num(l.in_min) +
        '" onchange="' + S_('{in_min:+this.value}') + '"></div>' +
      '<div><label>Input max</label><input type="number" step="any" value="' + num(l.in_max) +
        '" onchange="' + S_('{in_max:+this.value}') + '"></div>' +
      '<div><label>Output min</label><input type="number" step="any" value="' + num(l.out_min) +
        '" onchange="' + S_('{out_min:+this.value}') + '"></div>' +
      '<div><label>Output max</label><input type="number" step="any" value="' + num(l.out_max) +
        '" onchange="' + S_('{out_max:+this.value}') + '"></div>' +
      '<div><label>Curve</label><select onchange="' + S_('{curve:this.value}') + '">' +
        curves + '</select></div>' +
      '<div><label>Amount</label><input type="number" step="0.1" value="' + l.amount +
        '" onchange="' + S_('{amount:+this.value}') + '"></div>' +
      '<div><label>Smoothing</label><input type="number" step="0.05" min="0" max="0.99" value="' +
        l.smoothing + '" onchange="' + S_('{smoothing:+this.value}') + '"></div>' +
    '</div>' +
    '<div class="row" style="margin-top:10px">' +
      '<label style="margin:0">invert<input type="checkbox" ' + (l.invert ? 'checked' : '') +
        ' onchange="' + S_('{invert:this.checked}') + '"></label>' +
      '<label style="margin:0">enabled<input type="checkbox" ' + (l.enabled ? 'checked' : '') +
        ' onchange="' + S_('{enabled:this.checked}') + '"></label>' +
      '<button class="small" onclick="cmd(\'learn\',{route:' + r.index + ',leg:' + l.index +
        '})">learn input range</button>' +
      '<button class="small danger" onclick="cmd(\'del_leg\',{route:' + r.index + ',leg:' +
        l.index + '})">remove leg</button>' +
    '</div></div>';
}

function setRoute(i, fields){ cmd('set_route', {route:i, fields:fields}); }
function setLeg(r, l, fields){ cmd('set_leg', {route:r, leg:l, fields:fields}); }

function drawSetup(){
  var d = S.destinations, h = [];
  h.push('<div class="card"><strong>Input</strong><div class="grid" style="margin-top:8px">' +
    '<div><label>Listen on (0.0.0.0 = every adapter)</label><input value="' + esc(S.input.host) +
      '" onchange="cmd(\'set_input\',{host:this.value})"></div>' +
    '<div><label>Port</label><input type="number" value="' + S.input.port +
      '" onchange="cmd(\'set_input\',{port:+this.value})"></div></div></div>');
  ['adm','yosc','custom'].forEach(function(p){
    var x = d[p] || {host:'127.0.0.1', port:0, enabled:false};
    h.push('<div class="card"><strong>Output · ' + p + '</strong>' +
      '<div class="grid" style="margin-top:8px">' +
      '<div><label>Host</label><input value="' + esc(x.host) +
        '" onchange="cmd(\'set_dest\',{protocol:\'' + p + '\',host:this.value})"></div>' +
      '<div><label>Port</label><input type="number" value="' + x.port +
        '" onchange="cmd(\'set_dest\',{protocol:\'' + p + '\',port:+this.value})"></div>' +
      '<div><label>Enabled</label><input type="checkbox" ' + (x.enabled ? 'checked' : '') +
        ' onchange="cmd(\'set_dest\',{protocol:\'' + p + '\',enabled:this.checked})"></div>' +
      '</div></div>');
  });
  h.push('<div class="card row">' +
    '<button onclick="cmd(\'send_all\')">Send all now</button>' +
    '<button onclick="cmd(\'save\')">Save project</button></div>');
  document.getElementById('setup').innerHTML = h.join('');
}

poll();
setInterval(poll, 700);
</script>
</body>
</html>
"""
