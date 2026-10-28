import logging
import os
import sqlite3
import time
import re
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from google import genai

# ================= CONFIGURAÇÕES =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9021554152:AAEMyuoimiq1ljdtvNhFnjKmIiXL0vek7-Q")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6IVZJ0CchReLGLCbTFiHX-KFHbpGsQj8ueQtuHHZa6waA")
MEU_TELEGRAM_ID = 6159661624

ai_client = genai.Client(api_key=GEMINI_API_KEY)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

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

# ================= BACKUP LOCAL INTELIGENTE (SEM IA) =================
def extrair_dados_localmente(texto):
    # Procura por números no texto (ex: 45, 45.50, 1.200,50)
    texto_limpo = texto.replace(',', '.')
    numeros = re.findall(r'\d+(?:\.\d+)?', texto_limpo)
    
    valor = 0.0
    if numeros:
        # Pega o maior número ou o primeiro relevante
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
    CATEGORIA: (Escolha obrigatoriamente uma destas: Alimentação, Transporte, Lazer, Saúde, Moradia, Educação, Investimentos, Salário, Outros)
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
                
    # Se a IA falhar totalmente por sobrecarga, usa o extrator local automático!
    return extrair_dados_localmente(texto_mensagem)

# ================= COMANDOS E HANDLERS =================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MEU_TELEGRAM_ID:
        return
    
    mensagem_ajuda = (
        "🤖 **Assistente Financeiro Seguro Ativo!**\n\n"
        "Envie uma mensagem natural ou áudio (ex: *'Gastei 45 no supermercado no pix'*, *'Recebi 3000 de salário'*).\n\n"
        "**Comandos disponíveis:**\n"
        "• /resumo - Balanço total e por categorias do mês\n"
        "• /desfazer - Apaga o último registo guardado\n"
        "• /ajuda - Mostra esta lista de comandos"
    )
    await update.message.reply_text(mensagem_ajuda, parse_mode="Markdown")

async def cmd_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MEU_TELEGRAM_ID:
        return
        
    resumo, categorias = obter_resumo_mes()
    total_receitas = resumo["Receita"]
    total_despesas = resumo["Despesa"]
    saldo = total_receitas - total_despesas
    
    texto = (
        f"📊 **Balanço Financeiro do Mês**\n\n"
        f"📈 **Entradas:** R$ {total_receitas:.2f}\n"
        f"📉 **Saídas:** R$ {total_despesas:.2f}\n"
        f"💰 **Saldo Atual:** R$ {saldo:.2f}\n\n"
        f"📂 **Gastos por Categoria:**\n"
    )
    
    if categorias:
        for cat, total in categorias:
            texto += f"• {cat}: R$ {total:.2f}\n"
    else:
        texto += "• Nenhum gasto registado ainda.\n"

    await update.message.reply_text(texto, parse_mode="Markdown")

async def cmd_desfazer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MEU_TELEGRAM_ID:
        return
        
    removido = apagar_ultimo_registo()
    if removido:
        await update.message.reply_text(f"🗑️ Último registo apagado com sucesso:\n• {removido[1]} (R$ {removido[2]:.2f})")
    else:
        await update.message.reply_text("ℹ️ Não existem registos para apagar.")

async def tratar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != MEU_TELEGRAM_ID:
        await update.message.reply_text("Acesso não autorizado.")
        return

    texto_para_analisar = ""

    if update.message.text:
        texto_para_analisar = update.message.text
    elif update.message.voice or update.message.audio:
        await update.message.reply_text("🎙️ Processando áudio...")
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
        
        emoji = "📈" if tipo.lower() == "receita" else "💸"
        resposta = (
            f"{emoji} **Registro Salvo com Sucesso!**\n\n"
            f"• **Tipo:** {tipo}\n"
            f"• **Descrição:** {descricao}\n"
            f"• **Valor:** R$ {valor:.2f}\n"
            f"• **Categoria:** {categoria}\n"
            f"• **Forma de Pgto:** {forma_pagamento}"
        )
        await update.message.reply_text(resposta, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao processar registo: {str(e)}")

# ================= INICIALIZAÇÃO =================
if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ajuda", cmd_start))
    app.add_handler(CommandHandler("resumo", cmd_resumo))
    app.add_handler(CommandHandler("desfazer", cmd_desfazer))
    
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.AUDIO, tratar_mensagem))
    
    print("Bot a rodar com sucesso! Pressione Ctrl+C para parar.")
    app.run_polling(drop_pending_updates=True)
