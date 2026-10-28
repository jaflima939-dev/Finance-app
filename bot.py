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
        "🧹 /limpar - Apaga todos os dados de gastos e rendas\n"
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

async def cmd_limpar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MEU_TELEGRAM_ID:
        return
    
    conn = sqlite3.connect("financas.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transacoes")
    conn.commit()
    conn.close()
    
    await update.message.reply_text("🧹 **Histórico limpo com sucesso!** Todos os registros de gastos e rendas foram apagados para recomeçar.", parse_mode="Markdown")

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
    app.add_handler(CommandHandler("limpar", cmd_limpar))
    
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.AUDIO, tratar_mensagem))
    
    print("Bot a rodar com sucesso! Pressione Ctrl+C para parar.")
    app.run_polling(drop_pending_updates=True)
