# -*- coding: utf-8 -*-
"""
AGENTE OURO CAIXA - Vitrine de Joias Edition v7.1 (Fix ElementHandle)
✅ Correção: Navegação DOM via JS (Compatível com Playwright Python)
✅ Foco: UF + Download Inteligente (Atualizado > Padrão)
✅ RPA: Gravação Estável
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
import asyncio

# ============================================================================
# CONFIGURAÇÃO WINDOWS & PORTA
# ============================================================================
if sys.platform == 'win32':
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
# IMPORTS & PATHS
# ============================================================================
try:
    import pdfplumber
except ImportError:
    print("❌ Instale pdfplumber: pip install pdfplumber")
    sys.exit(1)

BASE = Path(__file__).parent.resolve()
CONFIG_FILE = BASE / "config.json"
MACRO_FILE = BASE / "macro_rpa.json"
DATA_DIR = BASE / "data"
PDF_DIR = DATA_DIR / "editais"
MANUAL_DIR = DATA_DIR / "manuais"

for d in [PDF_DIR, MANUAL_DIR]:
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
    "rpa_enabled": True,
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
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return {**DEFAULT_CONFIG, **loaded}
        except: pass
    return DEFAULT_CONFIG.copy()

# ============================================================================
# 🤖 LÓGICA DE DOWNLOAD INTELIGENTE (CORRIGIDA COM JS)
# ============================================================================

def download_macro_actions(page, cfg, pdf_links_collected):
    """
    Varre a tabela de resultados e baixa os PDFs usando injeção de JavaScript.
    Isso evita erros de API do Playwright Python e lida melhor com DOM dinâmico.
    Prioridade: 'Baixar Catálogo Atualizado' > 'Baixar Catálogo'
    """
    log("🔍 Varrendo lista de leilões para downloads...")
    
    # Aguarda a tabela carregar
    page.wait_for_timeout(4000) 
    
    # Script JS robusto para encontrar e clicar nos downloads
    js_script = """
    () => {
        let results = [];
        // Tenta encontrar linhas em tabelas ou divs de lista
        let rows = document.querySelectorAll('table tr');
        if (rows.length === 0) {
            rows = document.querySelectorAll('.lista-resultado-item, div[class*="linha"], div[class*="item"]');
        }

        rows.forEach((row, index) => {
            let select = row.querySelector('select');
            if (select) {
                let options = Array.from(select.options);
                let targetValue = null;
                let foundUpdated = false;

                // 1. Procura "Atualizado"
                for (let opt of options) {
                    let txt = opt.text.toLowerCase();
                    if (txt.includes('atualizado')) {
                        targetValue = opt.value;
                        foundUpdated = true;
                        break;
                    }
                }
                
                // 2. Se não achou, procura "Baixar Catálogo"
                if (!foundUpdated) {
                    for (let opt of options) {
                        let txt = opt.text.toLowerCase();
                        if (txt.includes('baixar') && txt.includes('catálogo')) {
                            targetValue = opt.value;
                            break;
                        }
                    }
                }

                if (targetValue) {
                    // Seleciona a opção
                    select.value = targetValue;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    
                    // Tenta achar botão irmão ou link
                    let next = select.nextElementSibling;
                    let clicked = false;
                    
                    // Se o próximo elemento for botão, clica
                    if (next && (next.tagName === 'BUTTON' || next.tagName === 'INPUT')) {
                        next.click();
                        clicked = true;
                    } 
                    // Se o próprio select disparar o download, ok.
                    // Às vezes há um ícone dentro da opção, mas o change costuma bastar.
                    
                    results.push({
                        row: index,
                        selected: targetValue,
                        clickedButton: clicked
                    });
                }
            }
        });
        return results;
    }
    """
    
    try:
        actions = page.evaluate(js_script)
        count = len(actions)
        log(f"   🎯 Identificados {count} itens para download na página.")
        
        if count > 0:
            # Aguarda um pouco para os downloads começarem a ser interceptados
            page.wait_for_timeout(3000) 
            
            # Se houver muitos itens, pode ser necessário rolar a página e repetir
            # Mas para a v7.1, vamos focar em garantir que o primeiro lote funcione.
            
    except Exception as e:
        log(f"❌ Erro ao executar script de download: {e}")

    log(f"✅ Processamento da lista finalizado. {count} downloads acionados via JS.")
    return count

def scrape_vitrine_playwright(base_url, cfg, recording_mode=False, stop_event=None):
    pdf_links = []
    
    if cfg.get("force_requests_only", False):
        return scrape_vitrine_requests(base_url, cfg)
    
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
            
            # Interceptador de Downloads Reais
            def handle_download(download):
                suggested = download.suggested_filename
                if suggested.endswith('.pdf'):
                    save_path = PDF_DIR / suggested
                    try:
                        # Garante que o diretório existe
                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        download.save_as(str(save_path))
                        pdf_links.append(f"local://{save_path}")
                        log(f"💾 Salvo: {suggested}")
                    except Exception as e:
                        log(f"❌ Erro ao salvar arquivo: {e}")
            
            page.on("download", handle_download)
            
            log(f"🌐 Acessando: {base_url[:60]}...")
            page.goto(base_url, timeout=cfg.get("request_timeout", 45)*1000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000) # Carregar JS
            
            if recording_mode:
                log("🔴 MODO GRAVAÇÃO ATIVO. O navegador está aberto. Faça o filtro manualmente.")
                st.warning("🔴 **Gravando...** Navegue no site. Quando terminar, clique em 'PARAR GRAVAÇÃO' na barra lateral desta tela (não feche o navegador).")
                
                while not stop_event.is_set():
                    time.sleep(1)
                
                log("⏹️ Gravação interrompida pelo usuário.")
                browser.close()
                return []

            # --- MODO AUTOMÁTICO ---
            
            # 1. Selecionar UF
            uf = cfg.get("target_uf", "SP")
            log(f"📍 Selecionando UF: {uf}")
            try:
                success_uf = False
                # Tenta via JS para evitar problemas de seletores
                js_uf = f"""
                () => {{
                    let selects = document.querySelectorAll('select');
                    for(let s of selects) {{
                        if(s.innerText.includes('UF') || s.name.toLowerCase().includes('uf') || s.id.toLowerCase().includes('uf')) {{
                            s.value = '{uf}';
                            s.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            return true;
                        }}
                    }}
                    return false;
                }}
                """
                found = page.evaluate(js_uf)
                if not found:
                    # Fallback tentando selecionar direto se soubermos o seletor genérico
                    try:
                        page.select_option("select", uf, timeout=3000)
                        success_uf = True
                    except: pass
                else:
                    success_uf = True
                    
                if success_uf:
                    log(f"✅ UF {uf} selecionada com sucesso.")
                else:
                    log(f"⚠️ Não foi possível localizar o campo UF automaticamente.")
                    
            except Exception as e:
                log(f"⚠️ Erro ao selecionar UF: {e}")

            # 2. Clicar em Filtrar (se houver botão explícito)
            try:
                # Tenta clicar via JS também para segurança
                js_click_filter = """
                () => {
                    let btns = document.querySelectorAll('button, input[type="button"]');
                    for(let b of btns) {
                        if(b.innerText.toLowerCase().includes('filtrar') || b.value.toLowerCase().includes('filtrar')) {
                            b.click();
                            return true;
                        }
                    }
                    return false;
                }
                """
                clicked = page.evaluate(js_click_filter)
                if clicked:
                    log("🔘 Botão 'Filtrar' acionado.")
                    page.wait_for_timeout(3000)
            except:
                pass 

            # 3. Baixar PDFs da Lista
            download_macro_actions(page, cfg, pdf_links)
            
            # Dá um tempo extra para todos os downloads iniciarem
            page.wait_for_timeout(5000)
            
            browser.close()
            log(f"✅ Playwright finalizado. {len(pdf_links)} arquivos capturados no total.")
            
    except ImportError:
        log("⚠️ Playwright não encontrado. Usando fallback requests.")
        return scrape_vitrine_requests(base_url, cfg)
    except Exception as e:
        log(f"❌ ERRO Crítico Playwright: {type(e).__name__}: {str(e)[:150]}")
        if cfg.get("playwright_debug"):
            log(traceback.format_exc()[:400])
        return []
    
    return pdf_links

def scrape_vitrine_requests(base_url, cfg):
    log("🔄 Tentando fallback requests (limitado para sites dinâmicos)...")
    try:
        r = requests.get(base_url, headers=get_headers(), timeout=30)
        urls = re.findall(r'href=["\'](.*?\.pdf)["\']', r.text, re.I)
        log(f"⚠️ Requests encontrou {len(urls)} links estáticos.")
        return urls
    except Exception as e:
        log(f"❌ Erro requests: {e}")
        return []

# ============================================================================
# PROCESSAMENTO DE DADOS
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
        except ImportError:
            pass 
        except Exception:
            pass
    return text

def parse_items(text, cfg):
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
            "desc": line.strip()[:150],
            "weight_g": round(weight, 2),
            "karat": karat,
            "pure_weight_g": round(pure_weight, 2),
            "start_bid": round(bid, 2)
        })
    return items

def calculate_viability(item, gold_price, cfg):
    fin = cfg.get("finance", DEFAULT_CONFIG["finance"])
    est_final = item["start_bid"] * fin["bid_multiplier"]
    fees = est_final * (fin["auction_fee_pct"] / 100)
    total_cost = est_final + fees + fin["fixed_costs"]
    market_val = item["pure_weight_g"] * gold_price
    profit = market_val - total_cost
    margin = (profit / total_cost * 100) if total_cost > 0 else 0
    
    return {
        **item,
        "est_final_bid": round(est_final, 2),
        "market_value": round(market_val, 2),
        "total_cost": round(total_cost, 2),
        "estimated_profit": round(profit, 2),
        "margin_pct": round(margin, 1),
        "viable": margin >= fin["min_margin_pct"]
    }

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
    if not recording_mode:
        st.session_state.logs = []
    
    if not recording_mode:
        log("🚀 Iniciando ciclo v7.1 - Correção DOM JS")
        gold_price = get_gold_price(cfg)
        log(f"💰 Cotação Ouro 24k: R$ {gold_price:.2f}/g")
    else:
        gold_price = 420.0 

    base_url = cfg.get("base_url", DEFAULT_CONFIG["base_url"])
    
    if cfg.get("use_playwright", True) and not cfg.get("force_requests_only", False):
        pdf_sources = scrape_vitrine_playwright(base_url, cfg, recording_mode, stop_event)
    else:
        pdf_sources = scrape_vitrine_requests(base_url, cfg)
    
    if recording_mode:
        return [] 

    all_results = []
    processed_count = 0
    
    for source in pdf_sources[:cfg.get("max_pdfs", 50)]:
        if source.startswith("local://"):
            path = Path(source.replace("local://", ""))
        else:
            fname = f"vit_{int(time.time())}_{random.randint(100,999)}.pdf"
            path = PDF_DIR / fname
            try:
                r = requests.get(source, headers=get_headers(), timeout=30)
                if r.status_code == 200:
                    path.write_bytes(r.content)
                else:
                    continue
            except: continue
        
        if not path.exists(): continue
        
        text = extract_text_from_pdf(path, cfg)
        items = parse_items(text, cfg)
        
        for item in items:
            calc = calculate_viability(item, gold_price, cfg)
            if calc["viable"]:
                calc["source"] = f"📄 {path.name}"
                all_results.append(calc)
        
        processed_count += 1
        time.sleep(0.5) 

    seen = set()
    unique_results = []
    for r in all_results:
        key = (r["desc"][:60], r["weight_g"], r["start_bid"])
        if key not in seen:
            seen.add(key)
            unique_results.append(r)
    
    st.session_state.results = unique_results
    
    if not recording_mode:
        if unique_results:
            log(f"🏁 Sucesso! {len(unique_results)} oportunidades em {processed_count} PDFs.")
            msg = f"*🥇 Oportunidades Ouro:* {len(unique_results)}\nOuro: R$ {gold_price:.2f}\n"
            for i, r in enumerate(unique_results[:5]):
                msg += f"{i+1}. {r['desc'][:40]}... Lucro: R$ {r['estimated_profit']:.0f}\n"
            send_whatsapp(msg, cfg)
        else:
            log(f"📊 Nenhuma oportunidade >= {cfg['finance']['min_margin_pct']}% encontrada.")
    
    return unique_results

# ============================================================================
# INTERFACE STREAMLIT
# ============================================================================

def main():
    st.set_page_config(page_title="🥇 Agente Vitrine Ouro v7.1", layout="wide", page_icon=":coin:")
    
    if "cfg" not in st.session_state: st.session_state.cfg = load_config()
    if "logs" not in st.session_state: st.session_state.logs = []
    if "results" not in st.session_state: st.session_state.results = []
    if "recording" not in st.session_state: st.session_state.recording = False
    if "stop_event" not in st.session_state: 
        st.session_state.stop_event = threading.Event()

    with st.sidebar:
        st.title("⚙️ Configurações")
        
        with st.expander("🤖 Automação & RPA", expanded=True):
            st.checkbox("✅ Usar Playwright", value=st.session_state.cfg["use_playwright"], key="chk_pw_1")
            st.checkbox("🧠 Habilitar Macro", value=st.session_state.cfg.get("rpa_enabled", True), key="chk_rpa_1")
            st.checkbox("🔍 Debug (Ver Navegador)", value=st.session_state.cfg["playwright_debug"], key="chk_dbg_1")
            st.checkbox("⚡ Apenas Requests", value=st.session_state.cfg.get("force_requests_only", False), key="chk_req_1")
            
            st.divider()
            st.caption("🎓 Treinamento")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔴 GRAVAR", type="primary", use_container_width=True, key="btn_rec_start"):
                    st.session_state.recording = True
                    st.session_state.stop_event.clear()
                    st.rerun()
            
            with col2:
                if st.session_state.recording:
                    if st.button("⏹️ PARAR", type="secondary", use_container_width=True, key="btn_rec_stop"):
                        st.session_state.stop_event.set()
                        st.session_state.recording = False
                        st.success("✅ Gravação parada!")
                        st.rerun()
                else:
                    st.info("Pronto para gravar")

        with st.expander("🌐 Filtros de Busca", expanded=True):
            st.text_input("UF Alvo", value=st.session_state.cfg.get("target_uf", "SP"), key="inp_uf_1")
            st.text_input("Situação", value=st.session_state.cfg.get("target_situacao", "Aberto"), key="inp_sit_1")
            st.slider("Máx. PDFs", 5, 100, st.session_state.cfg["max_pdfs"], key="sl_max_1")
            
            st.session_state.cfg["target_uf"] = st.session_state.inp_uf_1
            st.session_state.cfg["target_situacao"] = st.session_state.inp_sit_1
            st.session_state.cfg["max_pdfs"] = st.session_state.sl_max_1
            st.session_state.cfg["use_playwright"] = st.session_state.chk_pw_1
            st.session_state.cfg["playwright_debug"] = st.session_state.chk_dbg_1
            st.session_state.cfg["force_requests_only"] = st.session_state.chk_req_1

        with st.expander("📱 WhatsApp"):
            wa = st.session_state.cfg["whatsapp"]
            st.text_input("Telefone", value=wa["phone"], key="inp_wa_1")
            st.text_input("API Key", value=wa["api_key"], type="password", key="inp_wa_key_1")
            st.session_state.cfg["whatsapp"]["phone"] = st.session_state.inp_wa_1
            st.session_state.cfg["whatsapp"]["api_key"] = st.session_state.inp_wa_key_1

        with st.expander("💰 Financeiro"):
            fin = st.session_state.cfg["finance"]
            c1, c2 = st.columns(2)
            with c1:
                st.number_input("Taxa (%)", value=float(fin["auction_fee_pct"]), key="num_tax_1")
                st.number_input("Mult. Lance", value=float(fin["bid_multiplier"]), key="num_mult_1")
            with c2:
                st.number_input("Custos Fixos (R$)", value=float(fin["fixed_costs"]), key="num_fix_1")
                st.number_input("Margem Mín (%)", value=float(fin["min_margin_pct"]), key="num_mar_1")
            
            fin["auction_fee_pct"] = st.session_state.num_tax_1
            fin["bid_multiplier"] = st.session_state.num_mult_1
            fin["fixed_costs"] = st.session_state.num_fix_1
            fin["min_margin_pct"] = st.session_state.num_mar_1

        st.divider()
        if st.button("💾 Salvar Config", use_container_width=True, key="btn_save_cfg"):
            if save_config(st.session_state.cfg):
                st.success("Salvo!")

    st.title("🥇 Agente Vitrine de Joias v7.1")
    st.caption("Download Inteligente via JS | Prioriza 'Catálogo Atualizado'")
    
    tab1, tab2, tab3 = st.tabs(["🚀 Executar", "📊 Resultados", "📜 Logs"])
    
    with tab1:
        if st.session_state.recording:
            st.error("🔴 **MODO GRAVAÇÃO ATIVO**\n\n1. O navegador abrirá.\n2. Faça o filtro de UF e baixe um catálogo manualmente.\n3. **NÃO FECHE O NAVEGADOR.**\n4. Volte aqui e clique em **PARAR** na barra lateral.")
            
            if st.button("ABRIR NAVEGADOR AGORA", type="primary", key="btn_open_rec"):
                with st.spinner("Iniciando navegador para gravação..."):
                    run_pipeline(st.session_state.cfg, recording_mode=True, stop_event=st.session_state.stop_event)
        else:
            st.info("**Fluxo Automático:**\n1. Seleciona UF\n2. Varre leilões\n3. Baixa 'Catálogo Atualizado' (prioridade)\n4. Analisa Ouro e Margem")
            
            if st.button("🔍 EXECUTAR ANÁLISE", type="primary", use_container_width=True, key="btn_run_main"):
                with st.spinner("Processando..."):
                    run_pipeline(st.session_state.cfg, recording_mode=False)
                    st.rerun()
        
        st.metric("Resultados Encontrados", len(st.session_state.results))

    with tab2:
        if st.session_state.results:
            df = st.dataframe(
                st.session_state.results,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "desc": st.column_config.TextColumn("Descrição", width="large"),
                    "weight_g": st.column_config.NumberColumn("Peso (g)", format="%.2f"),
                    "pure_weight_g": st.column_config.NumberColumn("Ouro Puro (g)", format="%.2f"),
                    "start_bid": st.column_config.NumberColumn("Lance Inicial", format="R$ %.2f"),
                    "estimated_profit": st.column_config.NumberColumn("💰 Lucro Est.", format="R$ %.2f"),
                    "margin_pct": st.column_config.ProgressColumn("Margem %", format="%.1f%%", min=0, max=100),
                    "source": st.column_config.TextColumn("Origem")
                }
            )
            st.download_button("📥 Baixar CSV", data=str(df), file_name="resultados.csv")
        else:
            st.info("Execute uma análise para ver os resultados.")

    with tab3:
        st.button("🗑️ Limpar Logs", key="btn_clear_logs")
        if st.session_state.btn_clear_logs:
            st.session_state.logs = []
            st.rerun()
            
        logs_container = st.container(height=500, border=True)
        with logs_container:
            for line in st.session_state.logs[-50:]:
                if "❌" in line: st.error(line)
                elif "⚠️" in line: st.warning(line)
                elif "✅" in line: st.success(line)
                else: st.code(line)

if __name__ == "__main__":
    main()