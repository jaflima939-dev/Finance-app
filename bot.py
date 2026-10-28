import logging
import os
import sqlite3
import time
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from google import genai

# ================= CONFIGURAÇÕES =================
TELEGRAM_BOT_TOKEN = "9021554152:AAEMyuoimiq1ljdtvNhFnjKmIiXL0vek7-Q"
GEMINI_API_KEY = "AQ.Ab8RN6IVZJ0CchReLGLCbTFiHX-KFHbpGsQj8ueQtuHHZa6waA"
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
            forma_pagamento TEXT
        )
    ''')
    conn.commit()
    conn.close()

def salvar_transacao(tipo, descricao, valor, forma_pagamento):
    conn = sqlite3.connect("financas.db")
    cursor = conn.cursor()
    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO transacoes (data_hora, tipo, descricao, valor, forma_pagamento)
        VALUES (?, ?, ?, ?, ?)
    ''', (data_hora, tipo, descricao, valor, forma_pagamento))
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
    conn.close()
    
    resumo = {"Receita": 0.0, "Despesa": 0.0}
    for tipo, total in resultados:
        if tipo.capitalize() in resumo:
            resumo[tipo.capitalize()] = total or 0.0
            
    return resumo

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

# ================= IA COM ROTAÇÃO E RETRY AUTOMÁTICO =================
def interpretar_mensagem(texto_mensagem):
    prompt = f"""
    Você é um assistente financeiro. Analise a seguinte mensagem sobre uma transação financeira:
    "{texto_mensagem}"

    Extraia exatamente as seguintes informações no formato chave: valor simples, sem formatação extra ou markdown:
    TIPO: (Receita ou Despesa)
    DESCRICAO: (uma breve descrição do gasto/ganho)
    VALOR: (apenas o número com ponto decimal, ex: 50.00)
    FORMA_PAGAMENTO: (Pix, Cartão de Crédito, Cartão de Débito, Espécie, Transferência ou Não Especificado)
    """
    
    modelos = ['gemini-2.5-flash', 'gemini-3.5-flash-lite', 'gemini-2.5-flash']
    
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
                return dados
            except Exception as e:
                if "503" in str(e) or "Unavailable" in str(e) or "404" in str(e):
                    time.sleep(1)
                    continue
                break
                
    raise Exception("Servidores com alta demanda. Tente novamente em instantes.")

# ================= COMANDOS E HANDLERS =================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MEU_TELEGRAM_ID:
        return
    
    mensagem_ajuda = (
        "🤖 **Assistente Financeiro Ativo!**\n\n"
        "Envie uma mensagem natural ou áudio com o seu gasto/ganho (ex: *'Gastei 40 no mercado'*, *'Recebi 1500 de salário'*).\n\n"
        "**Comandos disponíveis:**\n"
        "• /resumo - Mostra o balanço total deste mês\n"
        "• /desfazer - Apaga o último registo guardado\n"
        "• /ajuda - Mostra esta lista de comandos"
    )
    await update.message.reply_text(mensagem_ajuda, parse_mode="Markdown")

async def cmd_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MEU_TELEGRAM_ID:
        return
        
    resumo = obter_resumo_mes()
    total_receitas = resumo["Receita"]
    total_despesas = resumo["Despesa"]
    saldo = total_receitas - total_despesas
    
    texto = (
        f"📊 **Balanço Financeiro do Mês**\n\n"
        f"📈 **Entradas:** R$ {total_receitas:.2f}\n"
        f"📉 **Saídas:** R$ {total_despesas:.2f}\n"
        f"💰 **Saldo Atual:** R$ {saldo:.2f}"
    )
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
        
        uploaded_file = ai_client.files.upload(file=caminho_audio)
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[uploaded_file, "Transcreva este áudio e interprete os gastos/receitas."]
        )
        texto_para_analisar = response.text
        if os.path.exists(caminho_audio):
            os.remove(caminho_audio)

    try:
        dados = interpretar_mensagem(texto_para_analisar)
        tipo = dados.get('TIPO', 'Despesa')
        descricao = dados.get('DESCRICAO', 'Não especificado')
        valor = float(dados.get('VALOR', 0.0))
        forma_pagamento = dados.get('FORMA_PAGAMENTO', 'Não Especificado')
        
        salvar_transacao(tipo, descricao, valor, forma_pagamento)
        
        emoji = "📈" if tipo.lower() == "receita" else "💸"
        resposta = (
            f"{emoji} **Registro Salvo com Sucesso!**\n\n"
            f"• **Tipo:** {tipo}\n"
            f"• **Descrição:** {descricao}\n"
            f"• **Valor:** R$ {valor:.2f}\n"
            f"• **Forma de Pgto:** {forma_pagamento}"
        )
        await update.message.reply_text(resposta, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao processar mensagem: {str(e)}")

# ================= INICIALIZAÇÃO =================
if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Comandos registados PRIMEIRO para evitar conflitos
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ajuda", cmd_start))
    app.add_handler(CommandHandler("resumo", cmd_resumo))
    app.add_handler(CommandHandler("desfazer", cmd_desfazer))
    
    # Texto e áudio por último
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.AUDIO, tratar_mensagem))
    
    print("Bot a rodar com sucesso! Pressione Ctrl+C para parar.")
    app.run_polling(drop_pending_updates=True)
