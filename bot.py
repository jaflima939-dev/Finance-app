import logging
import os
import sqlite3
import time
import re
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from google import genai

# Dependências para geração de PDF
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ================= CONFIGURAÇÕES =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9021554152:AAEMyuoimiq1ljdtvNhFnjKmIiXL0vek7-Q")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6IVZJ0CchReLGLCbTFiHX-KFHbpGsQj8ueQtuHHZa6waA")
MEU_TELEGRAM_ID = 6159661624

ai_client = genai.Client(api_key=GEMINI_API_KEY)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Novas Categorias Personalizadas e Emojis
EMOJIS_CATEGORIAS = {
    "Transporte": "🚗",
    "Lazer": "🎉",
    "Despesas": "💸",
    "Farmácia": "💊",
    "Médico": "🩺",
    "Saúde": "🏥",
    "Outros": "📦",
    "Salário": "💼",
    "Investimentos": "📊"
}

# ================= BANCO DE DADOS =================
def init_db():
    conn = sqlite3.connect("financas.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT,
            tipo TEXT,
            descricao TEXT,
            valor REAL,
            categoria TEXT,
            forma_pagamento TEXT
        )
    ''')
    conn.commit()
    conn.close()

def salvar_transacao(tipo, descricao, valor, categoria, forma_pagamento):
    conn = sqlite3.connect("financas.db")
    cursor = conn.cursor()
    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO transacoes (data_hora, tipo, descricao, valor, categoria, forma_pagamento)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (data_hora, tipo, descricao, valor, categoria, forma_pagamento))
    conn.commit()
    conn.close()

def obter_resumo_mes():
    conn = sqlite3.connect("financas.db")
    cursor = conn.cursor()
    mes_atual = datetime.now().strftime("%Y-%m")
    
    cursor.execute('''
        SELECT tipo, SUM(valor) FROM transacoes 
        WHERE data_hora LIKE ? GROUP BY tipo
    ''', (f"{mes_atual}%",))
    
    resultados = cursor.fetchall()
    
    cursor.execute('''
        SELECT categoria, SUM(valor) FROM transacoes 
        WHERE data_hora LIKE ? AND tipo = 'Despesa' GROUP BY categoria
    ''', (f"{mes_atual}%",))
    categorias = cursor.fetchall()
    
    conn.close()
    
    resumo = {"Receita": 0.0, "Despesa": 0.0}
    for tipo, total in resultados:
        if tipo.capitalize() in resumo:
            resumo[tipo.capitalize()] = total or 0.0
            
    return resumo, categorias

def obter_todas_transacoes_mes():
    conn = sqlite3.connect("financas.db")
    cursor = conn.cursor()
    mes_atual = datetime.now().strftime("%Y-%m")
    cursor.execute('''
        SELECT data_hora, tipo, descricao, valor, categoria, forma_pagamento 
        FROM transacoes WHERE data_hora LIKE ? ORDER BY data_hora DESC
    ''', (f"{mes_atual}%",))
    linhas = cursor.fetchall()
    conn.close()
    return linhas

def apagar_ultimo_registo():
    conn = sqlite3.connect("financas.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, descricao, valor FROM transacoes ORDER BY id DESC LIMIT 1")
    ultimo = cursor.fetchone()
    if ultimo:
        cursor.execute("DELETE FROM transacoes WHERE id = ?", (ultimo[0],))
        conn.commit()
        conn.close()
        return ultimo
    conn.close()
    return None

# ================= GERADOR DE PDF =================
def gerar_pdf_relatorio(nome_arquivo="relatorio_financeiro.pdf"):
    resumo, categorias = obter_resumo_mes()
    transacoes = obter_todas_transacoes_mes()
    mes_nome = datetime.now().strftime("%m/%Y")

    doc = SimpleDocTemplate(
        nome_arquivo,
        pagesize=letter,
        rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#1E293B'),
        spaceAfter=6
    )
    
    sub_style = ParagraphStyle(
        'SubStyle',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#64748B'),
        spaceAfter=15
    )

    story = []
    story.append(Paragraph(f"Relatório Financeiro — {mes_nome}", title_style))
    story.append(Paragraph("Gerado automaticamente pelo Assistente Financeiro", sub_style))

    # Tabela Resumo Geral
    total_rec = resumo["Receita"]
    total_desp = resumo["Despesa"]
    saldo = total_rec - total_desp

    data_resumo = [
        ["Entradas Totais", f"R$ {total_rec:.2f}"],
        ["Saídas Totais", f"R$ {total_desp:.2f}"],
        ["Saldo do Mês", f"R$ {saldo:.2f}"]
    ]
    
    t_resumo = Table(data_resumo, colWidths=[250, 250])
    t_resumo.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#0F172A')),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
    ]))
    story.append(t_resumo)
    story.append(Spacer(1, 15))

    # Tabela de Totais por Categoria no PDF
    story.append(Paragraph("<b>Totais por Categoria (Despesas):</b>", styles['Heading2']))
    story.append(Spacer(1, 8))

    data_cat = [["Categoria", "Total Gasto (R$)"]]
    if categorias:
        for cat, total in categorias:
            data_cat.append([cat, f"R$ {total:.2f}"])
    else:
        data_cat.append(["Nenhuma despesa registrada", "R$ 0.00"])

    t_cat = Table(data_cat, colWidths=[300, 200])
    t_cat.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#334155')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
    ]))
    story.append(t_cat)
    story.append(Spacer(1, 15))

    # Tabela de Extrato Detalhado
    story.append(Paragraph("<b>Extrato Detalhado do Mês:</b>", styles['Heading2']))
    story.append(Spacer(1, 8))

    data_trans = [["Data/Hora", "Tipo", "Descrição", "Categoria", "Pgto", "Valor (R$)"]]
    for t in transacoes:
        data_f = datetime.strptime(t[0], "%Y-%m-%d %H:%M:%S").strftime("%d/%m %H:%M")
        sinal = "+" if t[1].lower() == "receita" else "-"
        data_trans.append([
            data_f,
            t[1],
            t[2][:20],
            t[4],
            t[5],
            f"{sinal} {t[3]:.2f}"
        ])

    t_extrato = Table(data_trans, colWidths=[80, 60, 135, 85, 75, 65])
    t_extrato.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F172A')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('FONTSIZE', (0,0), (-1,-1), 8.5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('ALIGN', (5,0), (5,-1), 'RIGHT'),
    ]))
    story.append(t_extrato)

    doc.build(story)
    return nome_arquivo

# ================= BACKUP LOCAL INTELIGENTE =================
def extrair_dados_localmente(texto):
    texto_limpo = texto.replace(',', '.')
    numeros = re.findall(r'\d+(?:\.\d+)?', texto_limpo)
    
    valor = 0.0
    if numeros:
        valor = float(numeros[-1])
        
    tipo = "Receita" if any(palavra in texto.lower() for palavra in ["recebi", "ganhei", "salário", "entrada", "pix recebido"]) else "Despesa"
    
    return {
        'TIPO': tipo,
        'DESCRICAO': texto,
        'VALOR': valor,
        'CATEGORIA': 'Outros',
        'FORMA_PAGAMENTO': 'Não Especificado'
    }

# ================= IA COM FALLBACK LOCAL =================
def interpretar_mensagem(texto_mensagem):
    prompt = f"""
    Você é um assistente financeiro pessoal avançado. Analise a seguinte mensagem:
    "{texto_mensagem}"

    Extraia exatamente as seguintes informações no formato chave: valor simples, sem formatação extra ou markdown:
    TIPO: (Receita ou Despesa)
    DESCRICAO: (breve descrição do gasto ou ganho)
    VALOR: (apenas o número com ponto decimal, ex: 50.00)
    CATEGORIA: (Escolha obrigatoriamente UMA destas opções exatas: Transporte, Lazer, Despesas, Farmácia, Médico, Saúde, Outros, Salário, Investimentos)
    FORMA_PAGAMENTO: (Pix, Cartão de Crédito, Cartão de Débito, Espécie, Transferência ou Não Especificado)
    """
    
    modelos = ['gemini-2.5-flash', 'gemini-3.5-flash-lite', 'gemini-1.5-flash']
    
    for modelo in modelos:
        for tentativa in range(2):
            try:
                response = ai_client.models.generate_content(
                    model=modelo,
                    contents=prompt
                )
                linhas = response.text.strip().split('\n')
                dados = {}
                for linha in linhas:
                    if ':' in linha:
                        chave, valor = linha.split(':', 1)
                        dados[chave.strip().upper()] = valor.strip()
                if 'VALOR' in dados and 'TIPO' in dados:
                    return dados
            except Exception as e:
                erro_msg = str(e)
                if "503" in erro_msg or "Unavailable" in erro_msg or "429" in erro_msg:
                    time.sleep(1)
                    continue
                break
                
    return extrair_dados_localmente(texto_mensagem)

# ================= COMANDOS E HANDLERS =================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MEU_TELEGRAM_ID:
        return
    
    mensagem_ajuda = (
        "🤖 **Assistente Financeiro Ativo!**\n\n"
        "Envie uma mensagem natural (ex: *'Gastei 45 de transporte no uber'*, *'Paguei 60 na farmácia'*).\n\n"
        "✨ **Comandos Disponíveis:**\n"
        "📊 /resumo - Balanço completo e gastos por categoria\n"
        "📄 /pdf - Gera o relatório em PDF com resumo por categoria e extrato\n"
        "🗑️ /desfazer - Apaga o último registro\n"
        "❓ /ajuda - Exibe este menu"
    )
    await update.message.reply_text(mensagem_ajuda, parse_mode="Markdown")

async def cmd_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MEU_TELEGRAM_ID:
        return
        
    resumo, categorias = obter_resumo_mes()
    total_receitas = resumo["Receita"]
    total_despesas = resumo["Despesa"]
    saldo = total_receitas - total_despesas
    
    emoji_saldo = "🟢" if saldo >= 0 else "🔴"
    
    texto = (
        f"📊 **Balanço Financeiro do Mês**\n\n"
        f"📈 **Entradas:** R$ {total_receitas:.2f}\n"
        f"📉 **Saídas:** R$ {total_despesas:.2f}\n"
        f"{emoji_saldo} **Saldo Atual:** R$ {saldo:.2f}\n\n"
        f"🏷️ **Gastos por Categoria:**\n"
    )
    
    if categorias:
        for cat, total in categorias:
            e_cat = EMOJIS_CATEGORIAS.get(cat, "📦")
            texto += f"{e_cat} **{cat}:** R$ {total:.2f}\n"
    else:
        texto += "• Nenhum gasto registrado este mês.\n"

    await update.message.reply_text(texto, parse_mode="Markdown")

async def cmd_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MEU_TELEGRAM_ID:
        return
        
    await update.message.reply_text("📄 *Gerando o relatório financeiro em PDF...*", parse_mode="Markdown")
    try:
        caminho_pdf = gerar_pdf_relatorio()
        await update.message.reply_document(
            document=open(caminho_pdf, 'rb'),
            filename=f"Relatorio_Financeiro_{datetime.now().strftime('%m_%Y')}.pdf",
            caption="📊 Aqui está o seu relatório em PDF atualizado com as categorias!"
        )
        if os.path.exists(caminho_pdf):
            os.remove(caminho_pdf)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao gerar PDF: {str(e)}")

async def cmd_desfazer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MEU_TELEGRAM_ID:
        return
        
    removido = apagar_ultimo_registo()
    if removido:
        await update.message.reply_text(f"🗑️ **Registro removido com sucesso:**\n• {removido[1]} (R$ {removido[2]:.2f})", parse_mode="Markdown")
    else:
        await update.message.reply_text("ℹ️ Não existem registros no histórico para apagar.")

async def tratar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != MEU_TELEGRAM_ID:
        await update.message.reply_text("Acesso não autorizado.")
        return

    texto_para_analisar = ""

    if update.message.text:
        texto_para_analisar = update.message.text
    elif update.message.voice or update.message.audio:
        await update.message.reply_text("🎙️ *Processando áudio...*", parse_mode="Markdown")
        arquivo_voz = await context.bot.get_file(update.message.voice.file_id)
        caminho_audio = "audio_temp.ogg"
        await arquivo_voz.download_to_drive(caminho_audio)
        
        try:
            uploaded_file = ai_client.files.upload(file=caminho_audio)
            response = ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[uploaded_file, "Transcreva este áudio e interprete os gastos/receitas."]
            )
            texto_para_analisar = response.text
        except Exception:
            texto_para_analisar = "Despesa 0.00"
            
        if os.path.exists(caminho_audio):
            os.remove(caminho_audio)

    try:
        dados = interpretar_mensagem(texto_para_analisar)
        tipo = dados.get('TIPO', 'Despesa')
        descricao = dados.get('DESCRICAO', texto_para_analisar)
        valor = float(dados.get('VALOR', 0.0))
        categoria = dados.get('CATEGORIA', 'Outros')
        forma_pagamento = dados.get('FORMA_PAGAMENTO', 'Não Especificado')
        
        salvar_transacao(tipo, descricao, valor, categoria, forma_pagamento)
        
        if tipo.lower() == "receita":
            emoji_tipo = "📈"
            tag_cor = "🟢 **ENTRADA**"
        else:
            emoji_tipo = "💸"
            tag_cor = "🔴 **SAÍDA**"

        emoji_cat = EMOJIS_CATEGORIAS.get(categoria, "📦")
        
        resposta = (
            f"{emoji_tipo} {tag_cor} **Registrada!**\n\n"
            f"📝 **Descrição:** {descricao}\n"
            f"💰 **Valor:** R$ {valor:.2f}\n"
            f"{emoji_cat} **Categoria:** {categoria}\n"
            f"💳 **Forma de Pgto:** {forma_pagamento}"
        )
        await update.message.reply_text(resposta, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao processar registro: {str(e)}")

# ================= INICIALIZAÇÃO =================
if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ajuda", cmd_start))
    app.add_handler(CommandHandler("resumo", cmd_resumo))
    app.add_handler(CommandHandler("pdf", cmd_pdf))
    app.add_handler(CommandHandler("relatorio", cmd_pdf))
    app.add_handler(CommandHandler("desfazer", cmd_desfazer))
    
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.AUDIO, tratar_mensagem))
    
    print("Bot a rodar com sucesso! Pressione Ctrl+C para parar.")
    app.run_polling(drop_pending_updates=True)
