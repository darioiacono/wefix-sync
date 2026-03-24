import asyncio
import json
import os
import re
import threading
import time
from flask import Flask, jsonify, render_template_string, request
from playwright.async_api import async_playwright
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

app = Flask(__name__)

# ── CONFIG ──────────────────────────────────────────────────────────────────
IFIX_URL      = "https://business.ifix-iphone.com/prices"
IFIX_EMAIL    = "dario.iacono@gmail.com"
IFIX_PASSWORD = "Dariow12"
SHEET_ID      = "1wotM5CB3hsU5suU8oKx28vXRSf8poLhjTQVvxQKjGSE"
CREDS_FILE    = "google_credentials.json"

# ── GLOBAL STATE ─────────────────────────────────────────────────────────────
sync_status = {
    "running": False,
    "log": [],
    "progress": 0,
    "total": 0,
    "done": False,
    "error": None,
    "result": None,
}

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    sync_status["log"].append(entry)
    print(entry)

# ── SCRAPER ──────────────────────────────────────────────────────────────────
async def scrape_ifix():
    log("🚀 Avvio browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page    = await context.new_page()

        # 1. LOGIN
        log("🔐 Login su ifix-iphone.com...")
        await page.goto("https://business.ifix-iphone.com/login", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        await page.screenshot(path="debug_login.png")

        # Trova email
        email_sel = None
        for sel in ['input[type="email"]', 'input[name="email"]', 'input[name="username"]',
                    'input[placeholder*="mail" i]', 'input[placeholder*="user" i]', 'input:first-of-type']:
            try:
                el = await page.wait_for_selector(sel, timeout=2000)
                if el:
                    email_sel = sel
                    break
            except:
                pass
        if not email_sel:
            html = await page.content()
            log(f"HTML login: {html[:3000]}")
            raise Exception("Campo email non trovato — controlla debug_login.png nella cartella wefix-sync")
        await page.fill(email_sel, IFIX_EMAIL)
        log(f"✅ Email inserita ({email_sel})")

        # Trova password
        for sel in ['input[type="password"]', 'input[name="password"]', 'input[name="pwd"]']:
            try:
                el = await page.wait_for_selector(sel, timeout=2000)
                if el:
                    await page.fill(sel, IFIX_PASSWORD)
                    log(f"✅ Password inserita ({sel})")
                    break
            except:
                pass

        # Submit
        submitted = False
        for sel in ['button[type="submit"]', 'input[type="submit"]',
                    'button:has-text("Accesso")', 'button:has-text("Login")',
                    'button:has-text("Entra")', 'button:has-text("Sign")',
                    '.btn-primary', '.btn-success', 'form button']:
            try:
                el = await page.wait_for_selector(sel, timeout=2000)
                if el:
                    await el.click()
                    submitted = True
                    log(f"✅ Click submit ({sel})")
                    break
            except:
                pass
        if not submitted:
            await page.keyboard.press("Enter")
            log("✅ Submit via Enter")

        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)
        await page.screenshot(path="debug_after_login.png")
        log(f"✅ Login OK — URL: {page.url}")

        # 2. VAI A /prices
        if "prices" not in page.url:
            await page.goto(IFIX_URL, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # 3. TROVA TUTTI I BRAND (tab / select / accordion)
        log("🔍 Analisi struttura pagina prezzi...")
        
        # Prova a trovare brand come tab, select o link
        brands_data = {}
        
        # Cerca tab o nav con brand
        brand_tabs = await page.query_selector_all('[role="tab"], .nav-link, .brand-tab, .tab-link')
        brand_select = await page.query_selector('select[name*="brand"], select#brand, select.brand-select')
        
        if brand_select:
            log("📋 Trovato selettore brand (dropdown)")
            options = await brand_select.query_selector_all('option')
            brand_names = []
            for opt in options:
                val = await opt.get_attribute('value')
                txt = await opt.inner_text()
                if val and val.strip() and txt.strip():
                    brand_names.append((val, txt.strip()))
            log(f"📦 Brand trovati: {[b[1] for b in brand_names]}")

            for val, name in brand_names:
                log(f"⏳ Scraping brand: {name}...")
                await brand_select.select_option(val)
                await page.wait_for_timeout(1500)
                brands_data[name] = await extract_price_table(page)
                log(f"   → {len(brands_data[name])} modelli trovati")
                sync_status["progress"] += 1

        elif brand_tabs:
            log(f"📋 Trovate {len(brand_tabs)} tab brand")
            for tab in brand_tabs:
                name = (await tab.inner_text()).strip()
                if not name:
                    continue
                log(f"⏳ Scraping brand: {name}...")
                await tab.click()
                await page.wait_for_timeout(1500)
                brands_data[name] = await extract_price_table(page)
                log(f"   → {len(brands_data[name])} modelli trovati")
                sync_status["progress"] += 1
        else:
            # Fallback: prendi tutto dalla pagina corrente come unico brand
            log("⚠️  Nessun selettore brand trovato — estraggo tabella corrente")
            # Cerca eventuali sezioni o heading per separare brand
            brands_data = await extract_all_brands_from_page(page)

        await browser.close()
        return brands_data

async def extract_price_table(page):
    """Estrae righe da tabella prezzi nella pagina corrente."""
    rows = []
    table_rows = await page.query_selector_all("table tbody tr, .price-row, .model-row")
    for row in table_rows:
        cells = await row.query_selector_all("td, .cell")
        if len(cells) >= 2:
            cell_texts = []
            for c in cells:
                txt = (await c.inner_text()).strip()
                cell_texts.append(txt)
            if any(cell_texts):
                rows.append(cell_texts)
    return rows

async def extract_all_brands_from_page(page):
    """Estrae brand separati da heading nella pagina."""
    brands = {}
    
    # Tenta di trovare sezioni per brand tramite heading
    content = await page.content()
    
    # Cerca heading + tabella
    headings = await page.query_selector_all("h1, h2, h3, h4, .brand-heading, .section-title")
    if headings:
        for h in headings:
            name = (await h.inner_text()).strip()
            if name:
                # Prende la tabella successiva
                table = await h.evaluate_handle("el => el.nextElementSibling")
                if table:
                    rows_els = await table.query_selector_all("tr, .row")
                    rows = []
                    for r in rows_els:
                        cells = await r.query_selector_all("td, th")
                        texts = [(await c.inner_text()).strip() for c in cells]
                        if any(texts):
                            rows.append(texts)
                    brands[name] = rows
    
    if not brands:
        # Ultimo fallback: singola tabella intera
        brands["Tutti"] = await extract_price_table(page)
    
    return brands

# ── GOOGLE SHEETS ─────────────────────────────────────────────────────────────
def write_to_sheets(brands_data):
    log("📊 Connessione a Google Sheets...")
    
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds  = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc     = gspread.authorize(creds)
    sh     = gc.open_by_key(SHEET_ID)
    
    existing_sheets = [ws.title for ws in sh.worksheets()]
    log(f"📋 Sheet esistenti: {existing_sheets}")
    
    results = {}
    for brand, rows in brands_data.items():
        log(f"✍️  Scrittura sheet: {brand} ({len(rows)} righe)...")
        
        # Crea sheet se non esiste
        if brand not in existing_sheets:
            ws = sh.add_worksheet(title=brand, rows=max(len(rows)+5, 50), cols=20)
            log(f"   + Sheet '{brand}' creato")
        else:
            ws = sh.worksheet(brand)
            ws.clear()
            log(f"   ~ Sheet '{brand}' svuotato e riscritto")
        
        if rows:
            ws.update("A1", rows)
        
        results[brand] = len(rows)
        sync_status["progress"] += 1
        time.sleep(0.5)  # Rate limit Google Sheets API
    
    return results

# ── VERIFICA PRIMI 3 SHEET ────────────────────────────────────────────────────
def verify_existing_sheets(brands_data):
    """Controlla se Apple, Samsung, Huawei nel sheet corrispondono ai dati scraped."""
    report = {}
    first_three = ["Apple", "Samsung", "Huawei"]
    
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds  = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    gc     = gspread.authorize(creds)
    sh     = gc.open_by_key(SHEET_ID)
    
    for brand in first_three:
        if brand not in [ws.title for ws in sh.worksheets()]:
            report[brand] = {"status": "missing", "msg": "Sheet non trovato"}
            continue
        
        ws = sh.worksheet(brand)
        sheet_data = ws.get_all_values()
        scraped    = brands_data.get(brand, [])
        
        if not sheet_data:
            report[brand] = {"status": "empty", "msg": "Sheet vuoto"}
        elif len(sheet_data) != len(scraped):
            report[brand] = {
                "status": "mismatch",
                "msg": f"Righe sheet: {len(sheet_data)}, righe sito: {len(scraped)}"
            }
        else:
            report[brand] = {"status": "ok", "msg": f"{len(sheet_data)} righe — corrispondono ✅"}
    
    return report

# ── TASK ASINCRONO ────────────────────────────────────────────────────────────
def run_sync():
    sync_status.update({"running": True, "log": [], "progress": 0, "done": False, "error": None, "result": None})
    try:
        # Step 1: Scraping
        log("━━━ FASE 1: Scraping prezzi ━━━")
        brands_data = asyncio.run(scrape_ifix())
        sync_status["total"] = len(brands_data)
        log(f"✅ Trovati {len(brands_data)} brand: {list(brands_data.keys())}")

        # Step 2: Verifica primi 3
        log("━━━ FASE 2: Verifica Apple/Samsung/Huawei ━━━")
        if os.path.exists(CREDS_FILE):
            verify_report = verify_existing_sheets(brands_data)
            for brand, info in verify_report.items():
                icon = "✅" if info["status"] == "ok" else "⚠️"
                log(f"  {icon} {brand}: {info['msg']}")
        else:
            log("⚠️  Nessun file credenziali Google — skip verifica")
            verify_report = {}

        # Step 3: Scrivi su Sheets
        if os.path.exists(CREDS_FILE):
            log("━━━ FASE 3: Scrittura Google Sheets ━━━")
            write_results = write_to_sheets(brands_data)
            log(f"✅ Scrittura completata per {len(write_results)} brand")
        else:
            log("⚠️  CREDS_FILE non trovato — salto scrittura su Sheets")
            write_results = {}

        sync_status["result"] = {
            "brands": list(brands_data.keys()),
            "rows": {b: len(r) for b, r in brands_data.items()},
            "verify": verify_report,
            "written": write_results,
        }
        log("🎉 SYNC COMPLETATA!")

    except Exception as e:
        import traceback
        sync_status["error"] = str(e)
        log(f"❌ ERRORE: {e}")
        log(traceback.format_exc())
    finally:
        sync_status["running"] = False
        sync_status["done"]    = True

# ── HTML TEMPLATE ─────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WeFix Sync</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@700;800&display=swap');

  :root {
    --green: #4CAF50;
    --green-dark: #388E3C;
    --green-light: #81C784;
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #8b949e;
    --red: #f85149;
    --yellow: #d29922;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'DM Mono', monospace;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 40px 20px;
  }

  .header {
    width: 100%;
    max-width: 860px;
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 40px;
  }

  .logo {
    width: 48px; height: 48px;
    background: var(--green);
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 24px;
  }

  h1 {
    font-family: 'Syne', sans-serif;
    font-size: 2rem;
    font-weight: 800;
    color: var(--text);
  }

  h1 span { color: var(--green); }

  .subtitle {
    color: var(--muted);
    font-size: 0.75rem;
    margin-top: 2px;
  }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 28px;
    width: 100%;
    max-width: 860px;
    margin-bottom: 20px;
  }

  .card-title {
    font-family: 'Syne', sans-serif;
    font-size: 0.85rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
    margin-bottom: 16px;
  }

  .btn {
    background: var(--green);
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 14px 32px;
    font-family: 'Syne', sans-serif;
    font-size: 1rem;
    font-weight: 700;
    cursor: pointer;
    transition: background 0.2s, transform 0.1s;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .btn:hover:not(:disabled) { background: var(--green-dark); transform: translateY(-1px); }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .btn-danger {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 10px 20px;
    font-size: 0.8rem;
  }

  .config-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 20px;
  }

  .field label {
    display: block;
    font-size: 0.7rem;
    color: var(--muted);
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .field input {
    width: 100%;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 14px;
    color: var(--text);
    font-family: 'DM Mono', monospace;
    font-size: 0.85rem;
    outline: none;
    transition: border-color 0.2s;
  }

  .field input:focus { border-color: var(--green); }

  .terminal {
    background: #010409;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    height: 320px;
    overflow-y: auto;
    font-size: 0.78rem;
    line-height: 1.7;
  }

  .terminal::-webkit-scrollbar { width: 6px; }
  .terminal::-webkit-scrollbar-track { background: transparent; }
  .terminal::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

  .log-line { color: var(--muted); }
  .log-line.ok { color: var(--green-light); }
  .log-line.err { color: var(--red); }
  .log-line.warn { color: var(--yellow); }
  .log-line.head { color: var(--text); font-weight: 500; }

  .progress-bar {
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    margin: 16px 0 8px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--green), var(--green-light));
    border-radius: 2px;
    transition: width 0.4s ease;
    width: 0%;
  }

  .progress-label {
    font-size: 0.7rem;
    color: var(--muted);
    text-align: right;
  }

  .results-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
    margin-top: 16px;
  }

  .result-chip {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
  }

  .result-chip .brand { font-weight: 500; font-size: 0.85rem; }
  .result-chip .count { color: var(--green); font-size: 1.3rem; font-family: 'Syne', sans-serif; font-weight: 800; }
  .result-chip .label { color: var(--muted); font-size: 0.65rem; }

  .verify-list { margin-top: 12px; }

  .verify-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.82rem;
  }

  .verify-item:last-child { border-bottom: none; }
  .badge { font-size: 1rem; }

  .actions { display: flex; gap: 12px; align-items: center; }

  #statusBadge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.72rem;
    padding: 4px 12px;
    border-radius: 20px;
    background: var(--border);
    color: var(--muted);
  }

  #statusBadge.running { background: rgba(76,175,80,0.15); color: var(--green); }
  #statusBadge.done    { background: rgba(76,175,80,0.25); color: var(--green-light); }
  #statusBadge.error   { background: rgba(248,81,73,0.15); color: var(--red); }

  .dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: currentColor;
  }

  .dot.pulse { animation: pulse 1.2s infinite; }

  @keyframes pulse {
    0%,100% { opacity: 1; }
    50%      { opacity: 0.3; }
  }

  .creds-warning {
    background: rgba(210,153,34,0.1);
    border: 1px solid rgba(210,153,34,0.3);
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 0.78rem;
    color: var(--yellow);
    margin-top: 16px;
  }
</style>
</head>
<body>

<div class="header">
  <div class="logo">🔧</div>
  <div>
    <h1>WeFix<span>.sync</span></h1>
    <div class="subtitle">ifix-iphone.com → Google Sheets</div>
  </div>
</div>

<!-- CONFIG -->
<div class="card">
  <div class="card-title">⚙️ Configurazione</div>
  <div class="config-grid">
    <div class="field">
      <label>Email iFix</label>
      <input id="cfgEmail" value="dario.iacono@gmail.com">
    </div>
    <div class="field">
      <label>Password iFix</label>
      <input id="cfgPassword" type="password" value="Dariow12">
    </div>
    <div class="field" style="grid-column:1/-1">
      <label>Google Sheets ID</label>
      <input id="cfgSheetId" value="1wotM5CB3hsU5suU8oKx28vXRSf8poLhjTQVvxQKjGSE">
    </div>
  </div>

  <div class="creds-warning">
    ⚠️ <strong>Credenziali Google richieste:</strong> scarica il file <code>google_credentials.json</code>
    dal tuo Service Account Google Cloud e mettilo nella stessa cartella dell'app.
    <a href="https://console.cloud.google.com/iam-admin/serviceaccounts" target="_blank" style="color:var(--yellow)">→ Google Cloud Console</a>
  </div>
</div>

<!-- CONTROLLI -->
<div class="card">
  <div class="card-title">🚀 Esecuzione</div>
  <div class="actions">
    <button class="btn" id="btnSync" onclick="startSync()">
      <span>▶</span> Avvia Sincronizzazione
    </button>
    <div id="statusBadge">
      <div class="dot"></div> In attesa
    </div>
  </div>

  <div class="progress-bar" style="margin-top:20px">
    <div class="progress-fill" id="progressFill"></div>
  </div>
  <div class="progress-label" id="progressLabel">—</div>
</div>

<!-- TERMINAL -->
<div class="card">
  <div class="card-title">📟 Log</div>
  <div class="terminal" id="terminal">
    <span style="color:#30363d">// In attesa di avvio...</span>
  </div>
</div>

<!-- RISULTATI -->
<div class="card" id="resultsCard" style="display:none">
  <div class="card-title">📊 Risultati</div>

  <div id="verifySection" style="display:none">
    <div style="font-size:0.8rem;color:var(--muted);margin-bottom:8px">Verifica Apple / Samsung / Huawei</div>
    <div class="verify-list" id="verifyList"></div>
  </div>

  <div style="margin-top:20px">
    <div style="font-size:0.8rem;color:var(--muted);margin-bottom:12px">Brand sincronizzati</div>
    <div class="results-grid" id="resultsGrid"></div>
  </div>
</div>

<script>
let polling = null;

function startSync() {
  const email    = document.getElementById('cfgEmail').value;
  const password = document.getElementById('cfgPassword').value;
  const sheetId  = document.getElementById('cfgSheetId').value;

  document.getElementById('btnSync').disabled = true;
  document.getElementById('terminal').innerHTML = '';
  document.getElementById('resultsCard').style.display = 'none';
  setStatus('running', 'Avvio...');

  fetch('/start', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email, password, sheet_id: sheetId})
  }).then(() => {
    polling = setInterval(pollStatus, 1000);
  });
}

function pollStatus() {
  fetch('/status').then(r => r.json()).then(data => {
    renderLog(data.log);

    const pct = data.total > 0 ? Math.round((data.progress / (data.total * 2)) * 100) : 0;
    document.getElementById('progressFill').style.width = Math.min(pct, 100) + '%';
    document.getElementById('progressLabel').textContent =
      data.total > 0 ? `${data.progress} / ${data.total * 2} operazioni` : '…';

    if (!data.running && data.done) {
      clearInterval(polling);
      document.getElementById('btnSync').disabled = false;

      if (data.error) {
        setStatus('error', 'Errore');
        document.getElementById('progressFill').style.width = '100%';
        document.getElementById('progressFill').style.background = 'var(--red)';
      } else {
        setStatus('done', 'Completata ✓');
        document.getElementById('progressFill').style.width = '100%';
        renderResults(data.result);
      }
    }
  });
}

function renderLog(lines) {
  const t = document.getElementById('terminal');
  t.innerHTML = lines.map(line => {
    let cls = 'log-line';
    if (line.includes('✅') || line.includes('🎉')) cls += ' ok';
    else if (line.includes('❌')) cls += ' err';
    else if (line.includes('⚠️')) cls += ' warn';
    else if (line.includes('━━━')) cls += ' head';
    return `<div class="${cls}">${escHtml(line)}</div>`;
  }).join('');
  t.scrollTop = t.scrollHeight;
}

function renderResults(result) {
  if (!result) return;
  document.getElementById('resultsCard').style.display = 'block';

  // Verify
  if (result.verify && Object.keys(result.verify).length > 0) {
    document.getElementById('verifySection').style.display = 'block';
    const vl = document.getElementById('verifyList');
    vl.innerHTML = Object.entries(result.verify).map(([brand, info]) => {
      const icon = info.status === 'ok' ? '✅' : info.status === 'mismatch' ? '⚠️' : '❌';
      return `<div class="verify-item"><span class="badge">${icon}</span><strong>${brand}</strong><span style="color:var(--muted)">${escHtml(info.msg)}</span></div>`;
    }).join('');
  }

  // Brand grid
  const grid = document.getElementById('resultsGrid');
  grid.innerHTML = Object.entries(result.rows || {}).map(([brand, count]) => `
    <div class="result-chip">
      <div class="brand">${escHtml(brand)}</div>
      <div class="count">${count}</div>
      <div class="label">modelli</div>
    </div>
  `).join('');
}

function setStatus(state, label) {
  const badge = document.getElementById('statusBadge');
  const dot   = badge.querySelector('.dot');
  badge.className = 'statusBadge ' + state;
  badge.querySelector('.dot').className = 'dot' + (state === 'running' ? ' pulse' : '');
  badge.lastChild.textContent = ' ' + label;
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
</script>
</body>
</html>
"""

# ── ROUTES ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/start", methods=["POST"])
def start():
    if sync_status["running"]:
        return jsonify({"error": "già in esecuzione"}), 409
    
    data = request.get_json(force=True) or {}
    if data.get("email"):    app.config["IFIX_EMAIL"]    = data["email"]
    if data.get("password"): app.config["IFIX_PASSWORD"] = data["password"]
    if data.get("sheet_id"): app.config["SHEET_ID"]      = data["sheet_id"]
    
    t = threading.Thread(target=run_sync, daemon=True)
    t.start()
    return jsonify({"ok": True})

@app.route("/status")
def status():
    return jsonify(sync_status)

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🔧 WeFix Sync — avvio su http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=5000, use_reloader=False)
