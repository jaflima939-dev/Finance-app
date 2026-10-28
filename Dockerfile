FROM python:3.10-slim

WORKDIR /app

# Instalar dependências se tiver um requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o resto do código do projeto
COPY . .

# Comando para iniciar o seu bot (substitua 'bot.py' pelo nome do seu ficheiro principal)
CMD ["python", "bot.py"]
