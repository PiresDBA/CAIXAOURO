# -*- coding: utf-8 -*-
"""
AGENTE OURO CAIXA - Vitrine de Joias Edition v9.3 (Padrão Diamante Industrial)
✅ Motor Smart-Table: Agrupamento por linha visual e fechamento por peso por extenso
✅ Planilha Mestra: 100% dos Dados (Sem filtro prévio - Pronto para Power BI)
✅ WhatsApp Robusto: Tratamento de erros de API e relatórios formatados
✅ Cálculos Industriais: Taxas, Impostos, Desvalorização e Lucro Real
✅ Log em Tempo Real: Streaming Terminal com detalhes de extração
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
from collections import defaultdict

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
        "include": ["ouro", "barra", "moeda", "corrente", "pulseira", "anel", "alianca", "pingente", "cordao", "brinco"],
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
# SISTEMA DE LOG EM TEMPO REAL
# ============================================================================
class RealTimeLog:
    def __init__(self):
        if "logs" not in st.session_state:
            st.session_state.logs = []
        self.container = st.empty()
        
    def write(self, msg, level="INFO"):
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        color = "#00ff41"
        if level == "ERROR": color = "#ff4b4b"
        elif level == "WARN": color = "#ffa500"
        elif level == "DATA": color = "#00ccff"
        
        entry = f"<span style='color:{color}'>[{ts}] [{level}]</span> {msg}"
        st.session_state.logs.append(entry)
        
        logs_html = "<div style='background:#0e1117; padding:15px; border-radius:5px; height:400px; overflow-y:scroll; font-family:\"Fira Code\", monospace; font-size:12px; border:1px solid #333; box-shadow: inset 0 0 10px #000;'>"
        for log_line in st.session_state.logs[-50:]:
            logs_html += f"<div style='margin-bottom:2px; border-bottom:1px solid #1f2937;'>{log_line}</div>"
        logs_html += "</div>"
        
        self.container.markdown(logs_html, unsafe_allow_html=True)
        print(f"[{level}] {msg}")

logger = RealTimeLog()

def log(msg, level="INFO"):
    logger.write(msg, level)

# ============================================================================
# FUNÇÕES UTILITÁRIAS
# ============================================================================
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
            cfg = DEFAULT_CONFIG.copy()
            for k, v in loaded.items():
                if isinstance(v, dict) and k in cfg:
                    cfg[k].update(v)
                else:
                    cfg[k] = v
            return cfg
        except: pass
    return DEFAULT_CONFIG.copy()

# ============================================================================
# 🤖 RPA E DOWNLOAD
# ============================================================================

def download_macro_actions(page, cfg, pdf_links_collected, download_counter):
    log("🔍 Varrendo lista de leilões para downloads...", "INFO")
    page.wait_for_timeout(3000) 
    
    rows = page.query_selector_all("table tr")
    if not rows:
        rows = page.query_selector_all(".lista-resultado-item, div[class*='linha']")
    
    log(f"📋 Encontradas {len(rows)} linhas potenciais.", "DATA")
    
    count = 0
    for i, row in enumerate(rows):
        select_el = row.query_selector("select")
        
        if select_el:
            options = select_el.query_selector_all("option")
            target_option_value = None
            found_updated = False
            
            for opt in options:
                label = opt.inner_text().lower()
                if "atualizado" in label:
                    target_option_value = opt.get_attribute("value")
                    found_updated = True
                    break
            
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
                    seq_num = f"{download_counter['count']:03d}"
                    log(f"   📥 [{seq_num}] Download acionado na linha {i+1}.", "DATA")
                    page.wait_for_timeout(1500)
                    
                    if count >= cfg.get("max_pdfs", 50):
                        log("⚠️ Limite de PDFs atingido.", "WARN")
                        break
                except Exception as e:
                    log(f"⚠️ Erro ao interagir com item {i+1}: {str(e)[:50]}", "ERROR")
    
    log(f"✅ Varredura finalizada. {count} downloads solicitados.", "INFO")
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
                        log(f"💾 Salvo: {final_name}", "DATA")
                    except Exception as e:
                        log(f"❌ Erro ao salvar arquivo: {e}", "ERROR")
            
            page.on("download", handle_download)
            
            log(f"🌐 Acessando: {base_url[:60]}...", "INFO")
            page.goto(base_url, timeout=cfg.get("request_timeout", 45)*1000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            
            if recording_mode:
                log("🔴 MODO GRAVAÇÃO ATIVO.", "WARN")
                st.warning("🔴 **Gravando...** Navegue no site. Quando terminar, clique em 'PARAR' na sidebar.")
                while not stop_event.is_set():
                    time.sleep(1)
                browser.close()
                return []

            uf = cfg.get("target_uf", "SP")
            log(f"📍 Selecionando UF: {uf}", "INFO")
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
                log(f"⚠️ Aviso UF: {e}", "WARN")

            try:
                btn_filtrar = page.locator("button:has-text('Filtrar'), input[value='Filtrar']").first
                if btn_filtrar.is_visible():
                    btn_filtrar.click()
                    page.wait_for_timeout(2000)
            except: pass

            download_macro_actions(page, cfg, pdf_links, download_counter)
            browser.close()
            
    except ImportError:
        log("⚠️ Playwright não encontrado.", "ERROR")
    except Exception as e:
        log(f"❌ ERRO Playwright: {type(e).__name__}: {str(e)[:150]}", "ERROR")
    
    return pdf_links

# ============================================================================
# ⛏️ MOTOR DE EXTRAÇÃO INDUSTRIAL "SMART-TABLE" (PADRÃO DIAMANTE)
# ============================================================================

def get_gold_price(cfg):
    try:
        log("📡 Buscando cotação do Ouro em tempo real...", "INFO")
        r = requests.get(cfg.get("gold_api"), timeout=10, headers=get_headers())
        data = r.json()
        price = float(data.get("XAU", {}).get("ask", 0))
        if price > 0:
            log(f"💰 Cotação Obtida: R$ {price:.2f}/g (Ouro 24k)", "DATA")
            return price
        else:
            raise ValueError("Preço zero")
    except Exception as e:
        log(f"⚠️ Falha na API (Preço zero). Usando fallback R$ 420.00", "WARN")
        return 420.0

def extract_text_from_pdf(pdf_path, cfg):
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text()
                if t: 
                    text += t + "\n"
        if len(text.strip()) > 50:
            log(f"📄 Texto extraído de {pdf_path.name}: {len(text)} caracteres", "DATA")
            return text
    except Exception as e:
        log(f"⚠️ Erro leitura PDF (pdfplumber): {e}", "ERROR")
    
    if cfg.get("ocr_enabled", True) and len(text.strip()) < 50:
        log(f"🔍 Texto insuficiente. Tentando OCR em {pdf_path.name}...", "WARN")
        try:
            import pytesseract
            from pdf2image import convert_from_path
            images = convert_from_path(str(pdf_path), dpi=200)
            ocr_text = ""
            for img in images:
                ocr_text += pytesseract.image_to_string(img, lang="por+eng") + "\n"
            return ocr_text
        except ImportError:
            log("⚠️ Tesseract/PDF2Image não instalados.", "WARN")
        except Exception as e:
            log(f"❌ Erro OCR: {e}", "ERROR")
    
    return text

def parse_items_industrial(text, cfg, source_file):
    """
    Extrai registros completos baseados em estrutura visual e fechamento por peso por extenso.
    Retorna TODOS os registros encontrados para a planilha mestra.
    """
    items = []
    filters = cfg.get("filters", DEFAULT_CONFIG["filters"])
    
    # Padrão para detectar fim de registro: ( ... GRAMAS ... )
    # Ex: (DOZE GRAMAS E NOVENTA CENTIGRAMAS) ou (12,90 GRAMAS)
    pattern_end_marker = re.compile(r'\([^)]*[Gg][Rr][Aa][Mm][Aa][Ss][^)]*\)')
    
    # Padrões de extração
    pattern_lote = re.compile(r'^(\d+|[A-Z]\d+|LOTE\s*\d+)')
    pattern_value = re.compile(r'R\$\s*([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?)')
    pattern_weight_num = re.compile(r'(\d+[,.]?\d*)\s*[gG]')
    
    lines = text.split("\n")
    log(f"🔎 Analisando {len(lines)} linhas do arquivo {source_file}...", "DATA")
    
    current_record = {
        "lote": None,
        "descricao_parts": [],
        "valor": None,
        "anotacoes": [],
        "is_complete": False
    }
    
    records_found = 0
    
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
            
        # Verifica se a linha contém o marcador de fim de registro
        has_end_marker = bool(pattern_end_marker.search(line_clean))
        
        # Tenta identificar início de novo lote se ainda não tiver um ou se a linha parecer um novo início
        if current_record["lote"] is None or (pattern_lote.match(line_clean) and current_record["is_complete"]):
            # Se já tínhamos um registro completo, salvamos antes de começar o novo
            if current_record["lote"] is not None and current_record["is_complete"]:
                # Processa o registro anterior
                desc_full = " ".join(current_record["descricao_parts"])
                if current_record["valor"] and desc_full:
                    # Extrai peso numérico da descrição se possível
                    weight_match = pattern_weight_num.search(desc_full)
                    weight = float(weight_match.group(1).replace(",", ".")) if weight_match else 0.0
                    
                    # Determina quilate (padrão 18k se não especificado, ou tenta achar no texto)
                    karat = 18
                    if "24k" in desc_full.lower() or "24 K" in desc_full: karat = 24
                    elif "18k" in desc_full.lower() or "18 K" in desc_full: karat = 18
                    
                    pure_weight = weight * (karat / 24.0)
                    
                    items.append({
                        "origem_arquivo": source_file,
                        "lote": current_record["lote"],
                        "descricao_completa": desc_full,
                        "anotacoes": " ".join(current_record["anotacoes"]),
                        "peso_bruto_g": round(weight, 3),
                        "quilate": karat,
                        "peso_puro_g": round(pure_weight, 4),
                        "lance_inicial": current_record["valor"]
                    })
                    records_found += 1
            
            # Inicia novo registro
            current_record = {
                "lote": None,
                "descricao_parts": [],
                "valor": None,
                "anotacoes": [],
                "is_complete": False
            }
            
            # Tenta extrair lote da linha atual
            lot_match = pattern_lote.match(line_clean)
            if lot_match:
                current_record["lote"] = lot_match.group(1)
                # O restante da linha pode ser descrição
                rest = line_clean[len(lot_match.group(0)):].strip()
                if rest:
                    current_record["descricao_parts"].append(rest)
            else:
                # Se não achou lote mas está começando um bloco, assume que é continuação ou cabeçalho
                continue

        else:
            # Continuação do registro atual
            # Verifica se é valor
            val_match = pattern_value.search(line_clean)
            if val_match and current_record["valor"] is None:
                val_str = val_match.group(1)
                if ',' in val_str and '.' in val_str:
                    if val_str.rfind(',') > val_str.rfind('.'):
                        val_str = val_str.replace('.', '').replace(',', '.')
                    else:
                        val_str = val_str.replace(',', '')
                elif ',' in val_str:
                    val_str = val_str.replace(',', '.')
                try:
                    current_record["valor"] = float(val_str)
                except: pass
            else:
                # É descrição ou anotação
                if current_record["valor"] is None:
                    current_record["descricao_parts"].append(line_clean)
                else:
                    current_record["anotacoes"].append(line_clean)
        
        # Marca como completo se encontrou o marcador de peso por extenso
        if has_end_marker:
            current_record["is_complete"] = True

    # Processa o último registro se estiver completo
    if current_record["lote"] is not None and current_record["is_complete"]:
        desc_full = " ".join(current_record["descricao_parts"])
        if current_record["valor"] and desc_full:
            weight_match = pattern_weight_num.search(desc_full)
            weight = float(weight_match.group(1).replace(",", ".")) if weight_match else 0.0
            karat = 24 if "24k" in desc_full.lower() else 18
            pure_weight = weight * (karat / 24.0)
            
            items.append({
                "origem_arquivo": source_file,
                "lote": current_record["lote"],
                "descricao_completa": desc_full,
                "anotacoes": " ".join(current_record["anotacoes"]),
                "peso_bruto_g": round(weight, 3),
                "quilate": karat,
                "peso_puro_g": round(pure_weight, 4),
                "lance_inicial": current_record["valor"]
            })
            records_found += 1

    log(f"✅ {source_file}: {records_found} registros completos extraídos.", "DATA")
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
        "cotacao_ouro_usada": round(gold_price, 2),
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
        log("⚠️ Nenhum dado para gerar planilha.", "WARN")
        return
    
    df = pd.DataFrame(all_data)
    
    cols_order = [
        "origem_arquivo", "lote", "descricao_completa", "anotacoes", 
        "peso_bruto_g", "quilate", "peso_puro_g", "lance_inicial", 
        "est_lance_final", "taxa_leilao_5pct", "custos_fixos", 
        "desvalorizacao_est", "custo_total_industrial", "valor_mercado_ouro", 
        "lucro_liquido", "margem_liquida_pct", "viavel", "cotacao_ouro_usada"
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
                worksheet.column_dimensions[column_letter].width = min(adjusted_width, 30)
                
        log(f"✅ Planilha Mestra gerada: {path.name}", "INFO")
    except Exception as e:
        log(f"❌ Erro ao gerar Excel: {e}", "ERROR")

def send_whatsapp_report(total_count, viable_list, gold_price, cfg):
    wa = cfg.get("whatsapp", {})
    phone = wa.get("phone", "")
    api_key = wa.get("api_key", "")
    
    if not phone or not api_key:
        log("⚠️ Configuração de WhatsApp incompleta (Telefone ou API Key faltando).", "WARN")
        return False

    log("📱 Enviando relatório WhatsApp...", "INFO")
    
    viable_count = len(viable_list)
    date_str = datetime.now().strftime('%d/%m/%Y %H:%M')
    
    # Construção da mensagem
    header = f"*RELATÓRIO DIÁRIO - OURO CAIXA*\n"
    stats = f"📊 Itens Analisados: {total_count}\n💰 Cotação Ouro: R$ {gold_price:.2f}/g\n"
    footer = f"_{date_str}_\n📂 Planilha completa gerada no sistema."
    
    body = ""
    if viable_count > 0:
        body = f"\n✅ *{viable_count} OPORTUNIDADES (>15%)*\n\n"
        for i, item in enumerate(viable_list[:5], 1):
            desc_short = item['descricao_completa'][:40].replace('*', '')
            body += f"*{i}. Lote {item['lote']}*: {desc_short}...\n"
            body += f"   💰 Lucro: R$ {item['lucro_liquido']:.2f} ({item['margem_liquida_pct']}%)\n\n"
        if viable_count > 5:
            body += f"...e mais {viable_count - 5} oportunidades na planilha.\n"
    else:
        body = f"\n⚠️ *Nenhuma oportunidade encontrada acima de 15% de margem.*\nVerifique a planilha completa para detalhes.\n"

    full_msg = f"{header}{stats}{body}{footer}"
    
    # Codificação segura para URL
    encoded_msg = quote(full_msg)
    url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded_msg}&apikey={api_key}"
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            # Verifica se a resposta da API indica sucesso (algumas APIs retornam texto "Sent")
            if "Sent" in response.text or "error" not in response.text.lower():
                log("✅ WhatsApp enviado com sucesso!", "INFO")
                return True
            else:
                log(f"❌ Erro WhatsApp API: Resposta inesperada - {response.text[:100]}", "ERROR")
                return False
        else:
            log(f"❌ Erro WhatsApp API: Status {response.status_code} - {response.text[:100]}", "ERROR")
            return False
    except Exception as e:
        log(f"❌ Erro de conexão WhatsApp: {e}", "ERROR")
        return False

# ============================================================================
# PIPELINE PRINCIPAL
# ============================================================================

def run_pipeline(cfg, recording_mode=False, stop_event=None):
    if not recording_mode:
        st.session_state.results = []
        st.session_state.all_data_raw = []
    
    if not recording_mode:
        log("🚀 INICIANDO CICLO v9.3 - PADRÃO DIAMANTE", "INFO")
        gold_price = get_gold_price(cfg)
    else:
        gold_price = 420.0

    base_url = cfg.get("base_url", DEFAULT_CONFIG["base_url"])
    
    if cfg.get("use_playwright", True) and not cfg.get("force_requests_only", False):
        pdf_sources = scrape_vitrine_playwright(base_url, cfg, recording_mode, stop_event)
    else:
        pdf_sources = []
    
    if recording_mode:
        return []

    log(f"📂 Processando {len(pdf_sources)} PDFs...", "INFO")
    
    for idx, source in enumerate(pdf_sources[:cfg.get("max_pdfs", 50)]):
        if stop_event and stop_event.is_set():
            log("⛔ Processo interrompido.", "WARN")
            break
            
        if source.startswith("local://"):
            path = Path(source.replace("local://", ""))
        else: continue
        
        if not path.exists(): 
            log(f"❌ Arquivo não encontrado: {path}", "ERROR")
            continue
        
        log(f"🔄 [{idx+1}/{len(pdf_sources)}] {path.name}", "INFO")
        
        text = extract_text_from_pdf(path, cfg)
        if not text.strip():
            log(f"⚠️ Nenhum texto extraído de {path.name}", "WARN")
            continue
            
        items = parse_items_industrial(text, cfg, path.name)
        
        for item in items:
            calc = calculate_financials(item, gold_price, cfg)
            st.session_state.all_data_raw.append(calc) # TODOS os itens
            
            if calc["viavel"]:
                st.session_state.results.append(calc)
        
        time.sleep(0.1)

    # Gerar Planilha Mestra (SEMPRE)
    if st.session_state.all_data_raw:
        generate_master_excel(st.session_state.all_data_raw, MASTER_EXCEL_PATH)
    else:
        log("⚠️ Nenhum item extraído.", "WARN")
    
    # Enviar WhatsApp (SEMPRE)
    total_count = len(st.session_state.all_data_raw)
    send_whatsapp_report(total_count, st.session_state.results, gold_price, cfg)
    
    if not recording_mode:
        if st.session_state.results:
            log(f"🏁 SUCESSO! {len(st.session_state.results)} oportunidades identificadas.", "INFO")
        else:
            log(f"📊 Análise concluída. {total_count} itens verificados.", "INFO")
    
    return st.session_state.results

# ============================================================================
# INTERFACE STREAMLIT
# ============================================================================

def main():
    st.set_page_config(page_title="🥇 Ouro Intelligence v9.3", layout="wide", page_icon=":chart_with_upwards_trend:")
    
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;600&display=swap');
        .stMarkdown code { font-family: 'Fira Code', monospace; }
        div[data-testid="stMetricValue"] { font-size: 2rem; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

    if "cfg" not in st.session_state: st.session_state.cfg = load_config()
    if "logs" not in st.session_state: st.session_state.logs = []
    if "results" not in st.session_state: st.session_state.results = []
    if "all_data_raw" not in st.session_state: st.session_state.all_data_raw = []
    if "recording" not in st.session_state: st.session_state.recording = False
    if "stop_event" not in st.session_state: st.session_state.stop_event = threading.Event()

    with st.sidebar:
        st.title("⚙️ Configurações")
        
        with st.expander("🤖 Automação", expanded=True):
            st.checkbox("✅ Usar Playwright", value=st.session_state.cfg["use_playwright"], key="chk_pw_93")
            st.checkbox("🔍 Debug Visual", value=st.session_state.cfg["playwright_debug"], key="chk_dbg_93")
            
            st.divider()
            st.caption("🎓 Treinamento")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🔴 GRAVAR", type="primary", use_container_width=True, key="btn_rec_93"):
                    st.session_state.recording = True
                    st.session_state.stop_event.clear()
                    st.rerun()
            with c2:
                if st.session_state.recording:
                    if st.button("⏹️ PARAR", type="secondary", use_container_width=True, key="btn_stop_93"):
                        st.session_state.stop_event.set()
                        st.session_state.recording = False
                        st.rerun()

        with st.expander("🔍 Filtros de Extração", expanded=True):
            current_includes = ", ".join(st.session_state.cfg["filters"]["include"])
            new_includes = st.text_area("Termos para Incluir", value=current_includes, height=80)
            
            if st.button("Atualizar Filtros"):
                st.session_state.cfg["filters"]["include"] = [x.strip() for x in new_includes.split(",") if x.strip()]
                st.success("Filtros atualizados!")
            
            st.text_input("UF Alvo", value=st.session_state.cfg.get("target_uf", "SP"), key="inp_uf_93")
            st.slider("Máx. PDFs", 5, 100, st.session_state.cfg["max_pdfs"], key="sl_max_93")
            
            st.session_state.cfg["target_uf"] = st.session_state.inp_uf_93
            st.session_state.cfg["max_pdfs"] = st.session_state.sl_max_93

        with st.expander("💰 Parâmetros Financeiros"):
            fin = st.session_state.cfg["finance"]
            st.number_input("Taxa Leilão (%)", value=float(fin["auction_fee_pct"]), key="num_tax_93")
            st.number_input("Custos Fixos (R$)", value=float(fin["fixed_costs"]), key="num_fix_93")
            st.number_input("Desvalorização (%/mês)", value=float(fin["depreciation_pct_month"]), key="num_dep_93")
            st.number_input("Meses p/ Vender (Est)", value=int(fin.get("months_to_sell_estimate", 2)), key="num_mes_93")
            st.number_input("Margem Mínima Alvo (%)", value=float(fin["min_margin_pct"]), key="num_mar_93")
            
            fin["auction_fee_pct"] = st.session_state.num_tax_93
            fin["fixed_costs"] = st.session_state.num_fix_93
            fin["depreciation_pct_month"] = st.session_state.num_dep_93
            fin["months_to_sell_estimate"] = st.session_state.num_mes_93
            fin["min_margin_pct"] = st.session_state.num_mar_93

        st.divider()
        if st.button("💾 Salvar Tudo", use_container_width=True, key="btn_save_93"):
            if save_config(st.session_state.cfg): st.success("Salvo!")

    st.title("🥇 Ouro Intelligence v9.3")
    st.caption("Padrão Diamante Industrial | Smart-Table Extraction | Power BI Ready")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard Executivo", "📝 Planilha Mestra", "🔍 Oportunidades", "💻 Log em Tempo Real"])
    
    with tab1:
        if st.session_state.recording:
            st.error("🔴 **MODO GRAVAÇÃO ATIVO**")
            if st.button("ABRIR NAVEGADOR", type="primary", key="btn_open_rec_93"):
                run_pipeline(st.session_state.cfg, recording_mode=True, stop_event=st.session_state.stop_event)
        else:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Itens Analisados", len(st.session_state.all_data_raw))
            with col2:
                st.metric("Oportunidades (>15%)", len(st.session_state.results))
            with col3:
                avg_margin = sum([r['margem_liquida_pct'] for r in st.session_state.results]) / len(st.session_state.results) if st.session_state.results else 0
                st.metric("Margem Média", f"{avg_margin:.1f}%")
            with col4:
                last_gold = st.session_state.all_data_raw[0]['cotacao_ouro_usada'] if st.session_state.all_data_raw else 0
                st.metric("Cotação Ouro (Live)", f"R$ {last_gold:.2f}" if last_gold else "N/A")
            
            if st.button("🚀 EXECUTAR ANÁLISE COMPLETA", type="primary", use_container_width=True, key="btn_run_93"):
                run_pipeline(st.session_state.cfg)
                st.rerun()
            
            st.divider()
            
            if PLOTLY_AVAILABLE and st.session_state.all_data_raw:
                df_all = pd.DataFrame(st.session_state.all_data_raw)
                
                fig_hist = px.histogram(df_all, x="margem_liquida_pct", nbins=50, title="Distribuição de Rentabilidade (Todos os Itens)", color_discrete_sequence=['#00cc96'])
                fig_hist.add_vline(x=st.session_state.cfg["finance"]["min_margin_pct"], line_dash="dash", line_color="red", annotation_text="Meta 15%")
                st.plotly_chart(fig_hist, use_container_width=True)
                
                fig_scatter = px.scatter(df_all, x="peso_puro_g", y="lucro_liquido", color="margem_liquida_pct", size="est_lance_final", hover_data=["lote", "descricao_completa", "origem_arquivo"], title="Matriz de Decisão: Peso Puro vs Lucro")
                st.plotly_chart(fig_scatter, use_container_width=True)
                
                if st.session_state.results:
                    df_viable = pd.DataFrame(st.session_state.results).nlargest(10, 'lucro_liquido')
                    fig_bar = px.bar(df_viable, x="lote", y="lucro_liquido", title="Top 10 Maiores Lucros Líquidos", labels={'lote': 'Lote', 'lucro_liquido': 'Lucro (R$)'})
                    fig_bar.update_traces(marker_color='#00cc96')
                    st.plotly_chart(fig_bar, use_container_width=True)
            elif st.session_state.all_data_raw:
                st.warning("Instale plotly para ver os gráficos.")
            else:
                st.info("Execute uma análise para gerar o dashboard.")

    with tab2:
        st.header("📝 Planilha Mestra Completa")
        st.caption("Contém TODOS os itens extraídos (Pronto para Power BI).")
        
        if MASTER_EXCEL_PATH.exists() and st.session_state.all_data_raw:
            st.success(f"✅ Planilha gerada: `{MASTER_EXCEL_PATH.name}`")
            df_preview = pd.DataFrame(st.session_state.all_data_raw)
            st.dataframe(df_preview, use_container_width=True, height=600)
            
            with open(MASTER_EXCEL_PATH, "rb") as file:
                st.download_button("📥 Baixar Planilha Excel", file, file_name=MASTER_EXCEL_PATH.name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.info("Nenhuma planilha gerada ainda.")

    with tab3:
        st.header("🔍 Oportunidades Viáveis (>15%)")
        if st.session_state.results:
            df_res = pd.DataFrame(st.session_state.results)
            st.dataframe(
                df_res,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "descricao_completa": st.column_config.TextColumn("Descrição", width="large"),
                    "lucro_liquido": st.column_config.NumberColumn("💰 Lucro Líq.", format="R$ %.2f"),
                    "margem_liquida_pct": st.column_config.ProgressColumn("Margem %", format="%.1f%%"),
                    "custo_total_industrial": st.column_config.NumberColumn("Custo Total", format="R$ %.2f")
                }
            )
        else:
            st.info("Nenhuma oportunidade encontrada acima da meta.")

    with tab4:
        st.header("💻 Log do Sistema (Tempo Real)")
        if not st.session_state.logs:
            st.info("Os logs aparecerão aqui durante a execução.")
        else:
            logs_html = "<div style='background:#0e1117; padding:15px; border-radius:5px; height:600px; overflow-y:scroll; font-family:\"Fira Code\", monospace; font-size:12px; border:1px solid #333; box-shadow: inset 0 0 10px #000;'>"
            for log_line in st.session_state.logs:
                logs_html += f"<div style='margin-bottom:2px; border-bottom:1px solid #1f2937;'>{log_line}</div>"
            logs_html += "</div>"
            st.markdown(logs_html, unsafe_allow_html=True)
        
        if st.button("Limpar Logs"):
            st.session_state.logs = []
            st.rerun()

if __name__ == "__main__":
    main()