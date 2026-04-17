# -*- coding: utf-8 -*-
"""
AGENTE OURO CAIXA - Vitrine de Joias Edition v3.0
✅ Scraping robusto com fallback em 3 camadas
✅ Anti-detecção + headers realistas
✅ Logs detalhados + modo debug visual
✅ OCR + filtro inteligente para ouro derretível
✅ WhatsApp + exportação JSON/CSV
"""
import os
import sys
import json
import time
import re
import random
import socket
import traceback
import requests
import streamlit as st
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urljoin

# ============================================================================
# CONFIGURAÇÃO DE PORTA (evita conflito 8501)
# ============================================================================
def find_free_port(start=8501, attempts=10):
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start

FREE_PORT = find_free_port()
os.environ["STREAMLIT_SERVER_PORT"] = str(FREE_PORT)

# ============================================================================
# IMPORTS
# ============================================================================
import pdfplumber

# ============================================================================
# PATHS
# ============================================================================
BASE = Path(__file__).parent.resolve()
CONFIG_FILE = BASE / "config.json"
DATA_DIR = BASE / "data"
PDF_DIR = DATA_DIR / "editais"
MANUAL_DIR = DATA_DIR / "manuais"
RESULTS_DIR = DATA_DIR / "resultados"

for d in [PDF_DIR, MANUAL_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================================
# CONFIG PADRÃO
# ============================================================================
DEFAULT_CONFIG = {
    "base_url": "https://vitrinedejoias.caixa.gov.br/Paginas/default.aspx",
    "use_playwright": True,
    "playwright_headless": True,
    "playwright_debug": False,
    "force_requests_only": False,  # ⭐ NOVO: Pula Playwright totalmente
    "manual_pdf_links": [],
    "whatsapp": {"provider": "callmebot", "phone": "5511999999999", "api_key": ""},
    "finance": {
        "auction_fee_pct": 7.0,
        "fixed_costs": 180.0,
        "bid_multiplier": 1.35,
        "min_margin_pct": 15.0
    },
    "filters": {
        "include": ["ouro 18k", "ouro 24k", "barra", "moeda", "corrente", "pulseira", "anel", "alianca", "pingente", "cordao", "brinco ouro"],
        "exclude": ["pedra", "diamante", "zirconia", "esmeralda", "rubi", "safira", "prata", "folheado", "banhado", "fantasia", "aco", "cristal", "bijuteria"]
    },
    "gold_api": "https://economia.awesomeapi.com.br/last/XAU-BRL",
    "ocr_enabled": True,
    "request_timeout": 45,
    "max_pdfs": 20
}

# ============================================================================
# CONFIG FUNCTIONS
# ============================================================================
def load_config():
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return {**DEFAULT_CONFIG, **loaded}
        except: pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        st.error(f"❌ Erro ao salvar: {e}")
        return False

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Cache-Control": "max-age=0"
    }

# ============================================================================
# 🎭 PLAYWRIGHT SCRAPER (COM ANTI-DETECÇÃO)
# ============================================================================
def scrape_vitrine_playwright(base_url, cfg):
    pdf_links = []
    
    # Verificação prévia: se forçado modo requests, pula
    if cfg.get("force_requests_only", False):
        return scrape_vitrine_requests(base_url, cfg)
    
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            # Anti-detecção
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas", "--disable-gpu",
                "--window-size=1920,1080"
            ]
            
            headless = cfg.get("playwright_headless", True) and not cfg.get("playwright_debug", False)
            browser = p.chromium.launch(headless=headless, args=launch_args)
            
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=get_headers()["User-Agent"],
                locale="pt-BR", timezone_id="America/Sao_Paulo",
                extra_http_headers={k:v for k,v in get_headers().items() if k.lower()!='user-agent'}
            )
            
            # Bypass navigator.webdriver
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
                Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR','pt']});
            """)
            
            page = context.new_page()
            log(f"🌐 Navegando: {base_url[:70]}...")
            
            # Navegação com retry
            for attempt in range(3):
                try:
                    page.goto(base_url, timeout=cfg.get("request_timeout",45)*1000, wait_until="domcontentloaded")
                    page.wait_for_timeout(random.uniform(3000,6000))
                    break
                except Exception as e:
                    if attempt == 2: raise
                    log(f"🔄 Retry {attempt+1}/3...")
                    time.sleep(2**attempt)
            
            # Estratégia 1: Seletores CSS
            for selector in ["a[href*='.pdf']", "a[href*='edital']", "a[href*='lote']", "[role='link'][href*='pdf']"]:
                try:
                    for el in page.query_selector_all(selector):
                        href = el.get_attribute("href")
                        if href and ".pdf" in href.lower():
                            full = href if href.startswith("http") else urljoin(base_url, href)
                            full = full.split('?')[0].split('#')[0]
                            if full not in pdf_links and len(pdf_links) < cfg.get("max_pdfs",20):
                                pdf_links.append(full)
                except: continue
            
            # Estratégia 2: Regex no HTML
            content = page.content()
            for pattern in [r'href=["\']([^"\']*\.pdf[^"\']*)["\']', r'url=["\']([^"\']*\.pdf[^"\']*)["\']']:
                for m in re.findall(pattern, content, re.I):
                    full = m if m.startswith("http") else urljoin(base_url, m)
                    full = full.split('?')[0].split('#')[0]
                    if full not in pdf_links and len(pdf_links) < cfg.get("max_pdfs",20):
                        pdf_links.append(full)
            
            browser.close()
            log(f"✅ Playwright: {len(pdf_links)} PDFs encontrados")
            
    except ImportError:
        log("⚠️ Playwright não instalado. Usando fallback requests...")
        return scrape_vitrine_requests(base_url, cfg)
    except Exception as e:
        log(f"❌ ERRO Playwright: {type(e).__name__}: {str(e)[:150]}")
        log(f"🔍 DEBUG: {traceback.format_exc()[:400]}")
        return scrape_vitrine_requests(base_url, cfg)
    
    return pdf_links

# ============================================================================
# 🔄 FALLBACK: REQUESTS + BEAUTIFULSOUP
# ============================================================================
def scrape_vitrine_requests(base_url, cfg):
    pdf_links = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log("⚠️ BeautifulSoup não instalado: pip install beautifulsoup4")
        return []
    
    try:
        log(f"🔄 Fallback requests: {base_url[:70]}...")
        r = requests.get(base_url, headers=get_headers(), timeout=cfg.get("request_timeout",30))
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Busca em <a>, <iframe>, regex
        for tag in soup.find_all('a', href=True):
            href = tag['href'].lower()
            if '.pdf' in href or 'edital' in href or 'lote' in href:
                full = tag['href'] if tag['href'].startswith('http') else urljoin(base_url, tag['href'])
                full = full.split('?')[0].split('#')[0]
                if full not in pdf_links and len(pdf_links) < cfg.get("max_pdfs",20):
                    pdf_links.append(full)
        
        for tag in soup.find_all(['iframe','object'], src=True):
            src = tag.get('src','').lower()
            if '.pdf' in src:
                full = tag['src'] if tag['src'].startswith('http') else urljoin(base_url, tag['src'])
                if full not in pdf_links: pdf_links.append(full)
        
        for m in re.findall(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', r.text, re.I):
            full = m if m.startswith("http") else urljoin(base_url, m)
            full = full.split('?')[0].split('#')[0]
            if full not in pdf_links and len(pdf_links) < cfg.get("max_pdfs",20):
                pdf_links.append(full)
        
        log(f"✅ requests: {len(pdf_links)} PDFs encontrados")
    except Exception as e:
        log(f"❌ ERRO requests: {type(e).__name__}: {e}")
    
    return pdf_links

# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================
def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    full = f"[{ts}] {msg}"
    if "logs" in st.session_state:
        st.session_state.logs.append(full)
    print(full)

def get_gold_price_24k(cfg):
    try:
        r = requests.get(cfg.get("gold_api"), timeout=15, headers=get_headers())
        return float(r.json().get("XAU",{}).get("ask", 420.0))
    except:
        log("⚠️ Falha cotação ouro. Usando R$ 420/g")
        return 420.0

def download_pdf(url, save_path, cfg):
    try:
        r = requests.get(url, timeout=cfg.get("request_timeout",30), headers=get_headers())
        r.raise_for_status()
        save_path.write_bytes(r.content)
        return True
    except Exception as e:
        log(f"❌ DOWNLOAD: {url[:50]}... {e}")
        return False

def ocr_and_extract_text(pdf_path, cfg):
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t: text += t + "\n"
    except Exception as e:
        log(f"⚠️ pdfplumber: {e}")
    
    if cfg.get("ocr_enabled",True) and len(text.strip()) < 100:
        try:
            import pytesseract
            from pdf2image import convert_from_path
            for img in convert_from_path(str(pdf_path), dpi=200):
                text += pytesseract.image_to_string(img, lang="por+eng") + "\n"
        except ImportError:
            log("⚠️ OCR não disponível: pip install pytesseract pdf2image")
        except Exception as e:
            log(f"⚠️ OCR: {e}")
    return text

def parse_gold_items(text, cfg):
    items = []
    filters = cfg.get("filters", DEFAULT_CONFIG["filters"])
    
    for line in text.split("\n"):
        if not line.strip(): continue
        low = line.lower()
        if any(exc in low for exc in filters.get("exclude",[])): continue
        if not any(inc in low for inc in filters.get("include",[])): continue
        
        w = re.search(r'(\d+[,.]?\d*)\s*g', line)
        if not w: continue
        k = re.search(r'(\d+)\s*k', line)
        karat = int(k.group(1)) if k else 18
        if karat < 18: continue
        v = re.search(r'R\$\s*([\d.,]+)', line)
        if not v: continue
        
        try:
            weight = float(w.group(1).replace(",","."))
            pure = weight * (karat/24.0)
            bid = float(v.group(1).replace(".","").replace(",","."))
            items.append({
                "desc": line.strip()[:150], "weight_g": round(weight,2),
                "karat": karat, "pure_weight_g": round(pure,2), "start_bid": round(bid,2)
            })
        except: continue
    return items

def calc_viability(item, gold_24k, cfg):
    fin = cfg.get("finance", DEFAULT_CONFIG["finance"])
    est_bid = item["start_bid"] * fin["bid_multiplier"]
    fees = est_bid * (fin["auction_fee_pct"]/100)
    total = est_bid + fees + fin["fixed_costs"]
    market = item["pure_weight_g"] * gold_24k
    profit = market - total
    margin = (profit/total*100) if total>0 else 0
    return {
        **item, "est_final_bid": round(est_bid,2), "market_value": round(market,2),
        "total_cost": round(total,2), "estimated_profit": round(profit,2),
        "margin_pct": round(margin,1), "viable": margin >= fin["min_margin_pct"]
    }

def send_whatsapp(msg, cfg):
    wa = cfg.get("whatsapp",{})
    try:
        if wa.get("provider")=="callmebot":
            url = f"https://api.callmebot.com/whatsapp.php?phone={wa.get('phone')}&text={quote(msg)}&apikey={wa.get('api_key')}"
            return requests.get(url, timeout=15).status_code==200
        elif wa.get("provider")=="evolution":
            url = f"http://localhost:8080/message/sendText/{wa.get('instance','default')}"
            return requests.post(url, json={"number":wa.get("phone"),"text":msg}, headers={"apikey":wa.get("api_key")}, timeout=15).status_code==200
    except Exception as e:
        log(f"⚠️ WhatsApp: {e}")
    return False

def process_local_pdfs(cfg):
    results = []
    gold = get_gold_price_24k(cfg)
    for pdf in MANUAL_DIR.glob("*.pdf"):
        text = ocr_and_extract_text(pdf, cfg)
        for it in parse_gold_items(text, cfg):
            calc = calc_viability(it, gold, cfg)
            if calc["viable"]:
                calc["source"] = f"📁 local:{pdf.name}"
                results.append(calc)
    return results

# ============================================================================
# PIPELINE PRINCIPAL
# ============================================================================
def run_pipeline(cfg):
    st.session_state.logs = []
    st.session_state.results = []
    
    log("🚀 Iniciando ciclo - Vitrine de Joias")
    gold_24k = get_gold_price_24k(cfg)
    log(f"💰 Ouro 24k: R$ {gold_24k:.2f}/g | 18k: R$ {gold_24k*0.75:.2f}/g")
    
    base_url = cfg.get("base_url", DEFAULT_CONFIG["base_url"])
    
    # Scraping
    if cfg.get("use_playwright",True) and not cfg.get("force_requests_only",False):
        log("🎭 Usando Playwright")
        pdf_links = scrape_vitrine_playwright(base_url, cfg)
    else:
        log("🔄 Usando modo requests (fallback)")
        pdf_links = scrape_vitrine_requests(base_url, cfg)
    
    # Processa PDFs
    all_results = []
    for url in pdf_links[:cfg.get("max_pdfs",20)]:
        fname = f"vit_{int(time.time()*1000)}_{random.randint(100,999)}.pdf"
        path = PDF_DIR / fname
        if download_pdf(url, path, cfg):
            text = ocr_and_extract_text(path, cfg)
            for it in parse_gold_items(text, cfg):
                calc = calc_viability(it, gold_24k, cfg)
                if calc["viable"]:
                    calc["source"] = f"🌐 auto:{url[:45]}..."
                    all_results.append(calc)
        time.sleep(random.uniform(0.5,1.5))
    
    # Links manuais
    manual = cfg.get("manual_pdf_links",[])
    if isinstance(manual, str): manual = [manual]
    for url in manual:
        if not url.strip(): continue
        path = PDF_DIR / f"manual_{int(time.time()*1000)}.pdf"
        if download_pdf(url.strip(), path, cfg):
            text = ocr_and_extract_text(path, cfg)
            for it in parse_gold_items(text, cfg):
                calc = calc_viability(it, gold_24k, cfg)
                if calc["viable"]:
                    calc["source"] = f"🔗 link:{url[:40]}..."
                    all_results.append(calc)
    
    # PDFs locais + dedup
    all_results.extend(process_local_pdfs(cfg))
    seen, unique = set(), []
    for r in all_results:
        key = (r["desc"][:80], r["weight_g"], r["start_bid"])
        if key not in seen:
            seen.add(key); unique.append(r)
    
    st.session_state.results = unique
    
    # WhatsApp
    if unique:
        txt = f"*🥇 Vitrine Ouro - {len(unique)} Oportunidades*\nOuro 24k: R$ {gold_24k:.2f}/g\n\n"
        for i,r in enumerate(unique[:10],1):
            txt += f"*{i}. {r['desc'][:55]}...*\n⚖️ {r['weight_g']}g ({r['karat']}k) → Puro: {r['pure_weight_g']}g\n💰 R$ {r['est_final_bid']:,.0f} | 💵 +R$ {r['estimated_profit']:,.0f} ({r['margin_pct']}%)\n📁 {r['source']}\n\n"
        if len(unique)>10: txt += f"...e mais {len(unique)-10}.\n"
        txt += f"_{datetime.now().strftime('%d/%m %H:%M')}_\n"
        log("📱 WhatsApp: " + ("✅ Enviado" if send_whatsapp(txt,cfg) else "❌ Falha"))
    else:
        log(f"📊 Nenhuma oportunidade >= {cfg['finance']['min_margin_pct']}% margem")
    
    log(f"🏁 Finalizado: {len(unique)} oportunidades")
    return unique

# ============================================================================
# INTERFACE STREAMLIT
# ============================================================================
def main():
    st.set_page_config(page_title="🥇 Agente Vitrine Ouro", layout="wide", page_icon=":coin:")
    
    if "cfg" not in st.session_state: st.session_state.cfg = load_config()
    if "logs" not in st.session_state: st.session_state.logs = []
    if "results" not in st.session_state: st.session_state.results = []
    
    # Aviso de porta
    port = int(os.environ.get("STREAMLIT_SERVER_PORT",8501))
    if port != 8501:
        st.info(f"🔀 Porta 8501 ocupada. Rodando em **http://localhost:{port}**")
    
    with st.sidebar:
        st.title("⚙️ Configurações")
        
        with st.expander("🌐 Site", expanded=True):
            st.session_state.cfg["base_url"] = st.text_input("URL", value=st.session_state.cfg["base_url"])
            st.session_state.cfg["use_playwright"] = st.checkbox("✅ Playwright", value=st.session_state.cfg["use_playwright"])
            st.session_state.cfg["playwright_headless"] = st.checkbox("👻 Headless", value=st.session_state.cfg["playwright_headless"])
            st.session_state.cfg["playwright_debug"] = st.checkbox("🔍 Debug (mostra navegador)", value=st.session_state.cfg["playwright_debug"])
            # ⭐ NOVO: Forçar requests
            st.session_state.cfg["force_requests_only"] = st.checkbox("⚡ Forçar modo requests (sem Playwright)", value=st.session_state.cfg.get("force_requests_only",False), help="Use se o Playwright estiver com erro")
            st.session_state.cfg["max_pdfs"] = st.slider("📄 Máx. PDFs", 5, 50, st.session_state.cfg["max_pdfs"])
        
        with st.expander("📋 Links Manuais"):
            val = st.session_state.cfg["manual_pdf_links"]
            if isinstance(val,list): val = "\n".join(val)
            st.session_state.cfg["manual_pdf_links"] = st.text_area("URLs de PDF (um por linha)", value=val, height=80)
            st.caption("💡 Ou arraste PDFs para `data/manuais/`")
        
        with st.expander("📱 WhatsApp"):
            wa = st.session_state.cfg["whatsapp"]
            wa["provider"] = st.selectbox("Provedor", ["callmebot","evolution"], index=0 if wa["provider"]=="callmebot" else 1)
            wa["phone"] = st.text_input("Telefone (55+DDD)", value=wa["phone"])
            wa["api_key"] = st.text_input("API Key", value=wa["api_key"], type="password")
        
        with st.expander("💰 Financeiro", expanded=True):
            fin = st.session_state.cfg["finance"]
            c1,c2 = st.columns(2)
            with c1:
                fin["auction_fee_pct"] = st.number_input("Taxa (%)", 0.0,20.0, float(fin["auction_fee_pct"]), 0.5)
                fin["bid_multiplier"] = st.number_input("Mult. Lance", 1.0,3.0, float(fin["bid_multiplier"]), 0.05)
            with c2:
                fin["fixed_costs"] = st.number_input("Custos Fixos (R$)", 0.0,1000.0, float(fin["fixed_costs"]), 10.0)
                fin["min_margin_pct"] = st.number_input("Margem Mínima (%)", 5.0,50.0, float(fin["min_margin_pct"]), 1.0)
        
        with st.expander("🔍 Filtros"):
            filt = st.session_state.cfg["filters"]
            filt["include"] = [x.strip() for x in st.text_input("✅ Incluir", value=", ".join(filt["include"])).split(",") if x.strip()]
            filt["exclude"] = [x.strip() for x in st.text_input("❌ Excluir", value=", ".join(filt["exclude"])).split(",") if x.strip()]
        
        with st.expander("⚙️ Avançado"):
            st.session_state.cfg["ocr_enabled"] = st.checkbox("🔤 OCR", value=st.session_state.cfg["ocr_enabled"])
            st.session_state.cfg["request_timeout"] = st.slider("⏱️ Timeout (s)", 10,120, st.session_state.cfg["request_timeout"])
        
        st.divider()
        if st.button("💾 Salvar", type="primary", use_container_width=True):
            if save_config(st.session_state.cfg): st.success("✅ Salvo!")
        if st.button("🗑️ Resetar", use_container_width=True):
            st.session_state.cfg = DEFAULT_CONFIG.copy(); st.success("🔄 Resetado!")
    
    st.title("🥇 Agente Vitrine de Joias - Caixa")
    st.caption("Foco: ouro derretível com margem líquida ≥ configuração")
    
    tab1,tab2,tab3,tab4 = st.tabs(["🚀 Executar","📊 Resultados","📜 Logs","❓ Ajuda"])
    
    with tab1:
        st.info("**Fluxo:** 1️⃣ Navega no site → 2️⃣ Extrai PDFs → 3️⃣ OCR + filtro ouro → 4️⃣ Calcula margem → 5️⃣ WhatsApp")
        if st.button("🔍 EXECUTAR AGORA", type="primary", use_container_width=True, icon="🎯"):
            with st.spinner("🔄 Processando (1-4 min)..."):
                run_pipeline(st.session_state.cfg)
                st.rerun()
        col1,col2 = st.columns(2)
        with col1: st.metric("📁 Pasta Manuais", str(MANUAL_DIR.relative_to(BASE)))
        with col2: st.metric("📊 Resultados", len(st.session_state.results))
        
        # Status dependências
        try: import playwright; st.success("✅ Playwright: OK")
        except ImportError: 
            st.error("❌ Playwright: Não instalado")
            st.code("pip install playwright && playwright install chromium")
        try: from bs4 import BeautifulSoup; st.success("✅ BeautifulSoup: OK")
        except ImportError: st.warning("⚠️ BeautifulSoup: pip install beautifulsoup4")
    
    with tab2:
        if st.session_state.results:
            min_m = st.slider("Margem mínima (%)", 0.0,50.0, float(st.session_state.cfg["finance"]["min_margin_pct"]), 0.5)
            sort_by = st.selectbox("Ordenar", ["margin_pct","estimated_profit","pure_weight_g","est_final_bid"])
            filtered = sorted([r for r in st.session_state.results if r["margin_pct"]>=min_m], key=lambda x:x[sort_by], reverse=True)
            
            st.dataframe(filtered, use_container_width=True, hide_index=True, column_config={
                "desc": st.column_config.TextColumn("Descrição", width="large"),
                "weight_g": st.column_config.NumberColumn("Peso (g)", format="%.2f"),
                "pure_weight_g": st.column_config.NumberColumn("Puro (g)", format="%.2f"),
                "start_bid": st.column_config.NumberColumn("Lance", format="R$ %.2f"),
                "est_final_bid": st.column_config.NumberColumn("Est. Final", format="R$ %.0f"),
                "market_value": st.column_config.NumberColumn("Mercado", format="R$ %.2f"),
                "total_cost": st.column_config.NumberColumn("Custo", format="R$ %.2f"),
                "estimated_profit": st.column_config.NumberColumn("💰 Lucro", format="R$ %.2f"),
                "margin_pct": st.column_config.ProgressColumn("Margem", format="%.1f%%", min=0, max=100),
                "viable": st.column_config.CheckboxColumn("Viável"),
                "source": st.column_config.TextColumn("Origem")
            })
            
            c1,c2 = st.columns(2)
            with c1:
                st.download_button("📥 JSON", json.dumps(filtered,indent=2,ensure_ascii=False), f"resultados_{datetime.now().strftime('%Y%m%d_%H%M')}.json", "application/json", use_container_width=True)
            with c2:
                import csv,io
                if filtered:
                    buf = io.StringIO()
                    w = csv.DictWriter(buf, fieldnames=filtered[0].keys()); w.writeheader(); w.writerows(filtered)
                    st.download_button("📊 CSV", buf.getvalue(), f"resultados_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", "text/csv", use_container_width=True)
        else:
            st.info("🔍 Execute uma análise para ver resultados aqui.")
    
    with tab3:
        c1,c2 = st.columns([4,1])
        with c2:
            if st.button("🗑️ Limpar"): st.session_state.logs=[]; st.rerun()
            if st.button("📋 Copiar"): st.code("\n".join(st.session_state.logs[-50:]))
        with st.container(height=500,border=True):
            for line in st.session_state.logs[-100:]:
                if "[❌" in line: st.error(line)
                elif "[⚠️" in line: st.warning(line)
                elif "[✅" in line: st.success(line)
                else: st.code(line)
    
    with tab4:
        st.markdown("""
        ### 🛠️ Solução de Problemas
        
        #### ❌ Erro Playwright / `dispatcher_fiber`
        ```cmd
        cd D:\CAIXA-OURO
        venv\Scripts\activate
        pip uninstall playwright -y && pip cache purge
        pip install playwright==1.44.0
        playwright install chromium
        ```
        Ou marque **"⚡ Forçar modo requests"** na sidebar para pular o Playwright.
        
        #### ❌ Porta 8501 ocupada
        ```cmd
        :: Matar processo:
        for /f "tokens=5" %a in ('netstat -aon ^| findstr :8501 ^| findstr LISTENING') do taskkill /F /PID %a
        :: Ou usar outra porta:
        streamlit run app.py --server.port 8502
        ```
        
        #### ❌ Nenhum PDF encontrado
        - Ative **"🔍 Debug"** para ver o navegador abrindo
        - Verifique se o site `vitrinedejoias.caixa.gov.br` abre no seu navegador
        - Use **Links Manuais** para colar URLs diretas de PDF
        
        ---
        ### 💡 Dicas
        1. Primeira vez? Use **Debug** para validar acesso ao site
        2. PDFs manuais: arraste para `data/manuais/`
        3. WhatsApp: teste em https://api.callmebot.com/whatsapp.php?phone=5511999999999&text=Teste&apikey=SUA_KEY
        4. Ajuste filtros conforme editais da sua região
        """)
        st.caption(f"🥇 v3.0 | {datetime.now().strftime('%d/%m/%Y %H:%M')}")

if __name__ == "__main__":
    # Verifica dependências críticas
    for pkg in ["requests","pdfplumber","streamlit"]:
        try: __import__(pkg)
        except ImportError: print(f"❌ Instale: pip install {pkg}"); sys.exit(1)
    main()