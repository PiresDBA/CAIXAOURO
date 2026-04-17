# -*- coding: utf-8 -*-
"""
AGENTE OURO CAIXA - Vitrine de Joias Edition v8.1 (Dashboard Executivo Estável)
✅ Planilha Mestra Completa (Todos os registros)
✅ Dashboard Estilo Power BI (Gráficos, KPIs)
✅ Log Visual Typewriter (Estilo Obsidian/Terminal)
✅ Filtros Dinâmicos na UI (Inclusão de novos termos)
✅ Cálculos Industriais (Taxas, Impostos, Desvalorização)
✅ WhatsApp Automático (Foco em >15% lucro)
✅ Correção de KeyError e Estabilidade
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
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urljoin
import threading
import pandas as pd

# Imports Condicionais
try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

try:
    import pdfplumber
except ImportError:
    print("❌ Instale pdfplumber: pip install pdfplumber")
    sys.exit(1)

try:
    import openpyxl
except ImportError:
    print("❌ Instale openpyxl: pip install openpyxl")
    sys.exit(1)

# ============================================================================
# CONFIGURAÇÃO WINDOWS & PORTA
# ============================================================================
if sys.platform == 'win32':
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

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
# PATHS
# ============================================================================
BASE = Path(__file__).parent.resolve()
CONFIG_FILE = BASE / "config.json"
DATA_DIR = BASE / "data"
PDF_DIR = DATA_DIR / "editais"
MANUAL_DIR = DATA_DIR / "manuais"
RESULTS_DIR = DATA_DIR / "resultados"
MASTER_EXCEL_PATH = RESULTS_DIR / "analise_mestra_completa.xlsx"

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
    "force_requests_only": False,
    "manual_pdf_links": [],
    "whatsapp": {"provider": "callmebot", "phone": "5511999999999", "api_key": ""},
    "finance": {
        "auction_fee_pct": 5.0,
        "fixed_costs": 200.0,
        "depreciation_pct_month": 1.0,
        "months_to_sell_estimate": 2,
        "min_margin_pct": 15.0
    },
    "filters": {
        "include": ["ouro 18k", "ouro 24k", "barra", "moeda", "corrente", "pulseira", "anel", "alianca", "pingente", "cordao", "brinco ouro"],
        "exclude": ["pedra", "diamante", "zirconia", "esmeralda", "rubi", "safira", "prata", "folheado", "banhado", "fantasia", "aco", "cristal", "bijuteria"]
    },
    "gold_api": "https://economia.awesomeapi.com.br/last/XAU-BRL",
    "ocr_enabled": True,
    "request_timeout": 45,
    "max_pdfs": 50,
    "target_uf": "SP",
    "target_situacao": "Aberto"
}

# ============================================================================
# FUNÇÕES DE LOG E UTILITÁRIOS
# ============================================================================
def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    full = f"[{ts}] {msg}"
    if "logs" not in st.session_state:
        st.session_state.logs = []
    st.session_state.logs.append(full)
    print(full)

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive"
    }

def save_config(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        st.error(f"❌ Erro ao salvar: {e}")
        return False

def load_config():
    """Carrega config e garante que todas as chaves padrão existam."""
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            # Merge profundo para garantir chaves novas
            for key in DEFAULT_CONFIG:
                if key in loaded:
                    if isinstance(DEFAULT_CONFIG[key], dict):
                        config[key].update(loaded[key])
                    else:
                        config[key] = loaded[key]
        except Exception as e:
            print(f"Erro ao ler config: {e}")
    return config

# ============================================================================
# 🤖 LÓGICA DE RPA E DOWNLOAD INTELIGENTE
# ============================================================================

def download_macro_actions(page, cfg, pdf_links_collected, download_counter):
    log("🔍 Varrendo lista de leilões para downloads...")
    page.wait_for_timeout(3000) 
    
    rows = page.query_selector_all("table tr")
    if not rows:
        rows = page.query_selector_all(".lista-resultado-item, div[class*='linha']")
    
    count = 0
    for row in rows:
        select_el = row.query_selector("select")
        
        if select_el:
            options = select_el.query_selector_all("option")
            target_option_value = None
            found_updated = False
            
            # Prioridade: Atualizado
            for opt in options:
                label = opt.inner_text().lower()
                if "atualizado" in label:
                    target_option_value = opt.get_attribute("value")
                    found_updated = True
                    break
            
            # Secundário: Padrão
            if not found_updated:
                for opt in options:
                    label = opt.inner_text().lower()
                    if "baixar" in label and "catálogo" in label:
                        target_option_value = opt.get_attribute("value")
                        break
            
            if target_option_value:
                try:
                    select_el.select_option(value=target_option_value)
                    
                    page.evaluate("""
                        (el) => {
                            el.dispatchEvent(new Event('change'));
                            let next = el.nextElementSibling;
                            if(next && next.tagName === 'BUTTON') next.click();
                            let parent = el.parentElement;
                            if(parent) {
                                let btn = parent.querySelector('button, input[type="button"]');
                                if(btn && btn !== el) btn.click();
                            }
                        }
                    """, select_el)
                    
                    count += 1
                    download_counter['count'] += 1
                    log(f"   📥 [{download_counter['count']:03d}] Download acionado.")
                    page.wait_for_timeout(1500)
                    
                    if count >= cfg.get("max_pdfs", 50):
                        break
                except Exception as e:
                    log(f"⚠️ Erro ao interagir: {e}")
    
    log(f"✅ Varredura finalizada. {count} downloads solicitados.")
    return count

def scrape_vitrine_playwright(base_url, cfg, recording_mode=False, stop_event=None):
    pdf_links = []
    download_counter = {'count': 0}
    
    if cfg.get("force_requests_only", False):
        return []
    
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-gpu", "--window-size=1920,1080"
            ]
            
            headless = cfg.get("playwright_headless", True) and not cfg.get("playwright_debug", False) and not recording_mode
            browser = p.chromium.launch(headless=headless, args=launch_args)
            
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=get_headers()["User-Agent"],
                locale="pt-BR", timezone_id="America/Sao_Paulo"
            )
            
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)
            
            page = context.new_page()
            
            def handle_download(download):
                suggested = download.suggested_filename
                if suggested.endswith('.pdf'):
                    seq_num = f"{download_counter['count']:03d}"
                    clean_name = re.sub(r'[^\w\s.-]', '', suggested)
                    final_name = f"{seq_num}_{clean_name}"
                    save_path = PDF_DIR / final_name
                    try:
                        download.save_as(str(save_path))
                        pdf_links.append(f"local://{save_path}")
                        log(f"💾 Salvo: {final_name}")
                    except Exception as e:
                        log(f"❌ Erro ao salvar: {e}")
            
            page.on("download", handle_download)
            
            log(f"🌐 Acessando: {base_url[:60]}...")
            page.goto(base_url, timeout=cfg.get("request_timeout", 45)*1000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            
            if recording_mode:
                log("🔴 MODO GRAVAÇÃO ATIVO.")
                st.warning("🔴 **Gravando...** Navegue no site. Clique em 'PARAR' na sidebar.")
                while not stop_event.is_set():
                    time.sleep(1)
                browser.close()
                return []

            # Automação
            uf = cfg.get("target_uf", "SP")
            log(f"📍 Selecionando UF: {uf}")
            try:
                selectors_uf = ["select[name*='uf']", "select[id*='uf']", "select[class*='uf']"]
                success_uf = False
                for sel in selectors_uf:
                    if page.is_visible(sel):
                        page.select_option(sel, uf, timeout=3000)
                        success_uf = True
                        break
                if not success_uf:
                    page.evaluate(f"""
                        var selects = document.querySelectorAll('select');
                        for(var s of selects) {{
                            if(s.innerText.includes('UF') || s.name.includes('uf')) {{
                                s.value = '{uf}';
                                s.dispatchEvent(new Event('change'));
                            }}
                        }}
                    """)
            except Exception as e:
                log(f"⚠️ Aviso UF: {e}")

            try:
                btn_filtrar = page.locator("button:has-text('Filtrar'), input[value='Filtrar']").first
                if btn_filtrar.is_visible():
                    btn_filtrar.click()
                    page.wait_for_timeout(2000)
            except: pass

            download_macro_actions(page, cfg, pdf_links, download_counter)
            browser.close()
            
    except ImportError:
        log("⚠️ Playwright não encontrado.")
    except Exception as e:
        log(f"❌ ERRO Playwright: {type(e).__name__}: {str(e)[:150]}")
    
    return pdf_links

# ============================================================================
# PROCESSAMENTO DE DADOS E PLANILHA MESTRA
# ============================================================================

def get_gold_price(cfg):
    try:
        r = requests.get(cfg.get("gold_api"), timeout=10, headers=get_headers())
        return float(r.json().get("XAU", {}).get("ask", 420.0))
    except:
        return 420.0

def extract_text_from_pdf(pdf_path, cfg):
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t: text += t + "\n"
    except Exception as e:
        log(f"⚠️ Erro leitura PDF: {e}")
    
    if cfg.get("ocr_enabled", True) and len(text.strip()) < 50:
        try:
            import pytesseract
            from pdf2image import convert_from_path
            images = convert_from_path(str(pdf_path), dpi=200)
            for img in images:
                text += pytesseract.image_to_string(img, lang="por+eng") + "\n"
        except: pass
    return text

def parse_items(text, cfg, source_file):
    items = []
    filters = cfg.get("filters", DEFAULT_CONFIG["filters"])
    
    for line in text.split("\n"):
        if not line.strip(): continue
        low = line.lower()
        
        if any(exc in low for exc in filters.get("exclude", [])): continue
        if not any(inc in low for inc in filters.get("include", [])): continue
        
        w_match = re.search(r'(\d+[,.]?\d*)\s*g', line)
        if not w_match: continue
        weight = float(w_match.group(1).replace(",", "."))
        
        k_match = re.search(r'(\d+)\s*k', line)
        karat = int(k_match.group(1)) if k_match else 18
        if karat < 18: continue
        
        v_match = re.search(r'R\$\s*([\d.,]+)', line)
        if not v_match: continue
        bid_str = v_match.group(1).replace(".", "").replace(",", ".")
        try:
            bid = float(bid_str)
        except: continue
        
        pure_weight = weight * (karat / 24.0)
        items.append({
            "origem_arquivo": source_file,
            "descricao_raw": line.strip(),
            "peso_bruto_g": round(weight, 2),
            "quilate": karat,
            "peso_puro_g": round(pure_weight, 2),
            "lance_inicial": round(bid, 2)
        })
    return items

def calculate_financials(item, gold_price, cfg):
    fin = cfg.get("finance", DEFAULT_CONFIG["finance"])
    
    est_final_bid = item["lance_inicial"] * 1.35 
    auction_fee = est_final_bid * (fin["auction_fee_pct"] / 100)
    fixed_costs = fin["fixed_costs"]
    
    depreciation_months = fin.get("months_to_sell_estimate", 2)
    depreciation_val = est_final_bid * (fin["depreciation_pct_month"] / 100) * depreciation_months
    
    total_cost = est_final_bid + auction_fee + fixed_costs + depreciation_val
    market_value = item["peso_puro_g"] * gold_price
    net_profit = market_value - total_cost
    margin_pct = (net_profit / total_cost * 100) if total_cost > 0 else 0
    
    return {
        **item,
        "est_lance_final": round(est_final_bid, 2),
        "taxa_leilao_5pct": round(auction_fee, 2),
        "custos_fixos": round(fixed_costs, 2),
        "desvalorizacao_est": round(depreciation_val, 2),
        "custo_total_industrial": round(total_cost, 2),
        "valor_mercado_ouro": round(market_value, 2),
        "lucro_liquido": round(net_profit, 2),
        "margem_liquida_pct": round(margin_pct, 1),
        "viavel": margin_pct >= fin["min_margin_pct"]
    }

def generate_master_excel(all_data, path):
    if not all_data:
        return
    
    df = pd.DataFrame(all_data)
    cols_order = [
        "origem_arquivo", "descricao_raw", "peso_bruto_g", "quilate", "peso_puro_g",
        "lance_inicial", "est_lance_final", "taxa_leilao_5pct", "custos_fixos", 
        "desvalorizacao_est", "custo_total_industrial", "valor_mercado_ouro", 
        "lucro_liquido", "margem_liquida_pct", "viavel"
    ]
    
    final_cols = [c for c in cols_order if c in df.columns]
    df = df[final_cols]
    
    try:
        with pd.ExcelWriter(path, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Analise_Completa')
            workbook = writer.book
            worksheet = writer.sheets['Analise_Completa']
            
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except: pass
                adjusted_width = (max_length + 2)
                worksheet.column_dimensions[column_letter].width = min(adjusted_width, 25)
                
        log(f"✅ Planilha Mestra gerada: {path.name}")
    except Exception as e:
        log(f"❌ Erro ao gerar Excel: {e}")

def send_whatsapp(msg, cfg):
    wa = cfg.get("whatsapp", {})
    try:
        if wa.get("provider") == "callmebot":
            url = f"https://api.callmebot.com/whatsapp.php?phone={wa.get('phone')}&text={quote(msg)}&apikey={wa.get('api_key')}"
            return requests.get(url, timeout=10).status_code == 200
    except Exception as e:
        log(f"⚠️ Erro WhatsApp: {e}")
    return False

# ============================================================================
# PIPELINE PRINCIPAL
# ============================================================================

def run_pipeline(cfg, recording_mode=False, stop_event=None):
    st.session_state.results = []
    st.session_state.all_data_raw = []
    
    if not recording_mode:
        st.session_state.logs = []
        log("🚀 Iniciando ciclo v8.1 - Dashboard Executivo")
        gold_price = get_gold_price(cfg)
        log(f"💰 Cotação Ouro 24k: R$ {gold_price:.2f}/g")
    else:
        gold_price = 420.0

    base_url = cfg.get("base_url", DEFAULT_CONFIG["base_url"])
    
    if cfg.get("use_playwright", True) and not cfg.get("force_requests_only", False):
        pdf_sources = scrape_vitrine_playwright(base_url, cfg, recording_mode, stop_event)
    else:
        pdf_sources = []
    
    if recording_mode:
        return []

    for source in pdf_sources[:cfg.get("max_pdfs", 50)]:
        if source.startswith("local://"):
            path = Path(source.replace("local://", ""))
        else: continue
        
        if not path.exists(): continue
        
        text = extract_text_from_pdf(path, cfg)
        items = parse_items(text, cfg, path.name)
        
        for item in items:
            calc = calculate_financials(item, gold_price, cfg)
            st.session_state.all_data_raw.append(calc)
            
            if calc["viavel"]:
                st.session_state.results.append(calc)
        
        time.sleep(0.5)

    if st.session_state.all_data_raw:
        generate_master_excel(st.session_state.all_data_raw, MASTER_EXCEL_PATH)
    
    viable_count = len(st.session_state.results)
    total_analyzed = len(st.session_state.all_data_raw)
    
    msg = f"🤖 *Relatório Vitrine Ouro v8.1*\n"
    msg += f"📊 Analisados: {total_analyzed} itens\n"
    msg += f"💰 Ouro: R$ {gold_price:.2f}/g\n\n"
    
    if viable_count > 0:
        msg += f"✅ *{viable_count} OPORTUNIDADES (>15%)*\n"
        for i, r in enumerate(st.session_state.results[:5]):
            msg += f"{i+1}. {r['descricao_raw'][:40]}...\n   Lucro: R$ {r['lucro_liquido']:.2f} ({r['margem_liquida_pct']}%)\n"
        if viable_count > 5: msg += f"...e mais {viable_count-5}."
    else:
        msg += "⚠️ Nenhuma oportunidade com margem >15% encontrada desta vez."
    
    msg += f"\n_{datetime.now().strftime('%d/%m %H:%M')}_"
    send_whatsapp(msg, cfg)
    
    if not recording_mode:
        if viable_count > 0:
            log(f"🏁 Sucesso! {viable_count} oportunidades identificadas.")
        else:
            log(f"📊 Análise concluída. {total_analyzed} itens verificados, nenhum com margem >15%.")
    
    return st.session_state.results

# ============================================================================
# INTERFACE STREAMLIT
# ============================================================================

def main():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;600&display=swap');
        .stMarkdown code { font-family: 'Fira Code', monospace; background-color: #0e1117; color: #00ff41; border: 1px solid #1f2937; padding: 5px; border-radius: 4px; }
        .log-container { background-color: #0e1117; color: #00ff41; font-family: 'Fira Code', monospace; padding: 20px; border-radius: 10px; border: 1px solid #333; height: 400px; overflow-y: scroll; box-shadow: inset 0 0 20px #000; }
        .log-line { margin: 2px 0; animation: type 0.5s steps(40, end); }
        @keyframes type { from { width: 0; } }
        .metric-card { background: linear-gradient(135deg, #1f2937 0%, #111827 100%); padding: 20px; border-radius: 15px; color: white; text-align: center; border: 1px solid #374151; }
    </style>
    """, unsafe_allow_html=True)

    st.set_page_config(page_title="🥇 Ouro Intelligence v8.1", layout="wide", page_icon=":chart_with_upwards_trend:")
    
    if "cfg" not in st.session_state: st.session_state.cfg = load_config()
    if "logs" not in st.session_state: st.session_state.logs = []
    if "results" not in st.session_state: st.session_state.results = []
    if "all_data_raw" not in st.session_state: st.session_state.all_data_raw = []
    if "recording" not in st.session_state: st.session_state.recording = False
    if "stop_event" not in st.session_state: st.session_state.stop_event = threading.Event()

    with st.sidebar:
        st.title("⚙️ Configurações")
        
        with st.expander("🤖 Automação", expanded=True):
            st.checkbox("✅ Usar Playwright", value=st.session_state.cfg["use_playwright"], key="chk_pw_81")
            st.checkbox("🔍 Debug Visual", value=st.session_state.cfg["playwright_debug"], key="chk_dbg_81")
            
            st.divider()
            st.caption("🎓 Treinamento")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🔴 GRAVAR", type="primary", use_container_width=True, key="btn_rec_81"):
                    st.session_state.recording = True
                    st.session_state.stop_event.clear()
                    st.rerun()
            with c2:
                if st.session_state.recording:
                    if st.button("⏹️ PARAR", type="secondary", use_container_width=True, key="btn_stop_81"):
                        st.session_state.stop_event.set()
                        st.session_state.recording = False
                        st.rerun()

        with st.expander("🌐 Filtros de Busca", expanded=True):
            current_includes = ", ".join(st.session_state.cfg["filters"]["include"])
            new_includes = st.text_area("Termos para Incluir", value=current_includes, height=100, help="Adicione novos tipos de joias.")
            
            if st.button("Atualizar Filtros"):
                st.session_state.cfg["filters"]["include"] = [x.strip() for x in new_includes.split(",") if x.strip()]
                st.success("Filtros atualizados!")
            
            st.text_input("UF Alvo", value=st.session_state.cfg.get("target_uf", "SP"), key="inp_uf_81")
            st.slider("Máx. PDFs", 5, 100, st.session_state.cfg["max_pdfs"], key="sl_max_81")
            
            st.session_state.cfg["target_uf"] = st.session_state.inp_uf_81
            st.session_state.cfg["max_pdfs"] = st.session_state.sl_max_81

        with st.expander("💰 Parâmetros Financeiros"):
            fin = st.session_state.cfg["finance"]
            # Garante que as chaves existem antes de usar
            dep_val = fin.get("depreciation_pct_month", 1.0)
            months_val = fin.get("months_to_sell_estimate", 2)
            
            st.number_input("Taxa Leilão (%)", value=float(fin["auction_fee_pct"]), key="num_tax_81")
            st.number_input("Custos Fixos (R$)", value=float(fin["fixed_costs"]), key="num_fix_81")
            st.number_input("Desvalorização (%/mês)", value=float(dep_val), key="num_dep_81")
            st.number_input("Meses p/ Vender (Est)", value=int(months_val), key="num_mes_81")
            st.number_input("Margem Mínima Alvo (%)", value=float(fin["min_margin_pct"]), key="num_mar_81")
            
            fin["auction_fee_pct"] = st.session_state.num_tax_81
            fin["fixed_costs"] = st.session_state.num_fix_81
            fin["depreciation_pct_month"] = st.session_state.num_dep_81
            fin["months_to_sell_estimate"] = st.session_state.num_mes_81
            fin["min_margin_pct"] = st.session_state.num_mar_81

        st.divider()
        if st.button("💾 Salvar Tudo", use_container_width=True, key="btn_save_81"):
            if save_config(st.session_state.cfg): st.success("Salvo!")

    st.title("🥇 Ouro Intelligence v8.1")
    st.caption("Dashboard Executivo de Oportunidades | Análise Industrial Completa")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard Executivo", "📝 Planilha Mestra", "🔍 Detalhes Oportunidades", "💻 Log do Sistema"])
    
    with tab1:
        if st.session_state.recording:
            st.error("🔴 **MODO GRAVAÇÃO ATIVO**")
            if st.button("ABRIR NAVEGADOR", type="primary", key="btn_open_rec_81"):
                run_pipeline(st.session_state.cfg, recording_mode=True, stop_event=st.session_state.stop_event)
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Itens Analisados", len(st.session_state.all_data_raw))
            with col2:
                st.metric("Oportunidades (>15%)", len(st.session_state.results))
            with col3:
                avg_margin = 0.0
                if st.session_state.results:
                    avg_margin = sum([r['margem_liquida_pct'] for r in st.session_state.results]) / len(st.session_state.results)
                st.metric("Margem Média Oportunidades", f"{avg_margin:.1f}%")
            
            if st.button("🚀 EXECUTAR ANÁLISE COMPLETA", type="primary", use_container_width=True, key="btn_run_81"):
                with st.spinner("Processando editais, calculando impostos e gerando dashboard..."):
                    run_pipeline(st.session_state.cfg)
                    st.rerun()
            
            st.divider()
            
            if PLOTLY_AVAILABLE and st.session_state.all_data_raw:
                df_all = pd.DataFrame(st.session_state.all_data_raw)
                
                fig_hist = px.histogram(df_all, x="margem_liquida_pct", nbins=30, title="Distribuição de Margem de Lucro", color_discrete_sequence=['#00cc96'])
                fig_hist.add_vline(x=st.session_state.cfg["finance"]["min_margin_pct"], line_dash="dash", line_color="red", annotation_text="Meta 15%")
                st.plotly_chart(fig_hist, use_container_width=True)
                
                if st.session_state.results:
                    df_viable = pd.DataFrame(st.session_state.results)
                    fig_scatter = px.scatter(df_viable, x="peso_puro_g", y="lucro_liquido", size="est_lance_final", color="margem_liquida_pct", title="Relação Peso Puro vs Lucro Líquido", hover_data=["descricao_raw"])
                    st.plotly_chart(fig_scatter, use_container_width=True)
            elif st.session_state.all_data_raw:
                st.warning("Instale plotly para ver os gráficos: pip install plotly")
            else:
                st.info("Execute uma análise para gerar o dashboard.")

    with tab2:
        st.header("📝 Planilha Mestra Completa")
        st.caption("Contém TODOS os itens extraídos, com cálculos industriais.")
        
        if MASTER_EXCEL_PATH.exists() and st.session_state.all_data_raw:
            st.success(f"✅ Planilha gerada: `{MASTER_EXCEL_PATH.name}`")
            df_preview = pd.DataFrame(st.session_state.all_data_raw)
            st.dataframe(df_preview, use_container_width=True)
            
            with open(MASTER_EXCEL_PATH, "rb") as file:
                st.download_button("📥 Baixar Planilha Excel Profissional", file, file_name=MASTER_EXCEL_PATH.name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.info("Nenhuma planilha gerada ainda. Execute uma análise.")

    with tab3:
        st.header("🔍 Oportunidades Viáveis (>15%)")
        if st.session_state.results:
            df_res = pd.DataFrame(st.session_state.results)
            st.dataframe(
                df_res,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "descricao_raw": st.column_config.TextColumn("Descrição", width="large"),
                    "lucro_liquido": st.column_config.NumberColumn("💰 Lucro Líq.", format="R$ %.2f"),
                    "margem_liquida_pct": st.column_config.ProgressColumn("Margem %", format="%.1f%%", min=0, max=100),
                    "custo_total_industrial": st.column_config.NumberColumn("Custo Total", format="R$ %.2f")
                }
            )
        else:
            st.info("Nenhuma oportunidade encontrada acima da meta.")

    with tab4:
        st.header("💻 System Log")
        st.markdown("<div class='log-container'>", unsafe_allow_html=True)
        for line in st.session_state.logs[-50:]:
            safe_line = line.replace("<", "&lt;").replace(">", "&gt;")
            st.markdown(f"<div class='log-line'>{safe_line}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        
        if st.button("Limpar Logs"):
            st.session_state.logs = []
            st.rerun()

if __name__ == "__main__":
    main()