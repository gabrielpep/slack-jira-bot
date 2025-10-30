#!/usr/bin/env python3
"""
Bot Slack para criar tarefas no Jira automaticamente
Requer: pip install slack-bolt requests python-dotenv
"""

import os
import re
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import requests
from requests.auth import HTTPBasicAuth
import json

# Tenta carregar do .env local, senão usa variáveis de ambiente do sistema
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

class JiraIntegration:
    def __init__(self):
        self.jira_url = os.getenv('JIRA_URL').rstrip('/')
        self.jira_email = os.getenv('JIRA_EMAIL')
        self.jira_token = os.getenv('JIRA_API_TOKEN')
        self.project_key = os.getenv('JIRA_PROJECT_KEY')
        
        self.auth = HTTPBasicAuth(self.jira_email, self.jira_token)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
    
    def criar_tarefa(self, summary, description="", issue_type="Task", priority="Medium", labels=None):
        """Cria uma tarefa no Jira"""
        url = f"{self.jira_url}/rest/api/3/issue"
        
        payload = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [{
                        "type": "paragraph",
                        "content": [{
                            "type": "text",
                            "text": description
                        }]
                    }]
                },
                "issuetype": {"name": issue_type},
                "priority": {"name": priority}
            }
        }
        
        if labels:
            payload["fields"]["labels"] = labels
        
        try:
            response = requests.post(url, data=json.dumps(payload), 
                                   headers=self.headers, auth=self.auth)
            response.raise_for_status()
            result = response.json()
            return {
                "success": True,
                "key": result['key'],
                "url": f"{self.jira_url}/browse/{result['key']}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "details": response.text if 'response' in locals() else ""
            }

# Inicializa o app Slack
app = App(token=os.getenv("SLACK_BOT_TOKEN"))
jira = JiraIntegration()

# Comando slash: /create-task
@app.command("/create-task")
def handle_create_task_command(ack, command, respond):
    """Command to create task quickly"""
    ack()
    
    text = command['text'].strip()
    if not text:
        respond("❌ Please provide the task title.\nExample: `/create-task Fix login bug`")
        return
    
    respond("⏳ Creating task in Jira...")
    
    result = jira.criar_tarefa(
        summary=text,
        description=f"Task created via Slack by <@{command['user_id']}>",
        issue_type="Task",
        priority="Medium"
    )
    
    if result['success']:
        respond(f"✅ Task created successfully!\n🔗 *{result['key']}*: {result['url']}")
    else:
        respond(f"❌ Error creating task: {result['error']}")

# Interactive modal to create task with more details
@app.command("/new-task")
def open_modal(ack, body, client):
    """Opens modal with complete form"""
    ack()
    
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "tarefa_modal",
            "title": {"type": "plain_text", "text": "New Jira Task"},
            "submit": {"type": "plain_text", "text": "Create Task"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "titulo",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "titulo_input",
                        "placeholder": {"type": "plain_text", "text": "Ex: Implement authentication"}
                    },
                    "label": {"type": "plain_text", "text": "Title *"}
                },
                {
                    "type": "input",
                    "block_id": "descricao",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "descricao_input",
                        "multiline": True,
                        "placeholder": {"type": "plain_text", "text": "Describe the task details..."}
                    },
                    "label": {"type": "plain_text", "text": "Description"},
                    "optional": True
                },
                {
                    "type": "input",
                    "block_id": "tipo",
                    "element": {
                        "type": "static_select",
                        "action_id": "tipo_select",
                        "placeholder": {"type": "plain_text", "text": "Select type"},
                        "options": [
                            {"text": {"type": "plain_text", "text": "Task"}, "value": "Task"},
                            {"text": {"type": "plain_text", "text": "Bug"}, "value": "Bug"},
                            {"text": {"type": "plain_text", "text": "Story"}, "value": "Story"}
                        ],
                        "initial_option": {"text": {"type": "plain_text", "text": "Task"}, "value": "Task"}
                    },
                    "label": {"type": "plain_text", "text": "Type"}
                },
                {
                    "type": "input",
                    "block_id": "prioridade",
                    "element": {
                        "type": "static_select",
                        "action_id": "prioridade_select",
                        "placeholder": {"type": "plain_text", "text": "Select priority"},
                        "options": [
                            {"text": {"type": "plain_text", "text": "🔴 Highest"}, "value": "Highest"},
                            {"text": {"type": "plain_text", "text": "🟠 High"}, "value": "High"},
                            {"text": {"type": "plain_text", "text": "🟡 Medium"}, "value": "Medium"},
                            {"text": {"type": "plain_text", "text": "🟢 Low"}, "value": "Low"},
                            {"text": {"type": "plain_text", "text": "⚪ Lowest"}, "value": "Lowest"}
                        ],
                        "initial_option": {"text": {"type": "plain_text", "text": "🟡 Medium"}, "value": "Medium"}
                    },
                    "label": {"type": "plain_text", "text": "Priority"}
                },
                {
                    "type": "input",
                    "block_id": "labels",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "labels_input",
                        "placeholder": {"type": "plain_text", "text": "Ex: backend, urgent, api"}
                    },
                    "label": {"type": "plain_text", "text": "Labels (comma separated)"},
                    "optional": True
                }
            ]
        }
    )

@app.view("tarefa_modal")
def handle_submission(ack, body, client, view):
    """Processa o envio do formulário"""
    values = view["state"]["values"]
    
    titulo = values["titulo"]["titulo_input"]["value"]
    descricao = values["descricao"]["descricao_input"].get("value", "")
    tipo = values["tipo"]["tipo_select"]["selected_option"]["value"]
    prioridade = values["prioridade"]["prioridade_select"]["selected_option"]["value"]
    labels_text = values["labels"]["labels_input"].get("value", "")
    
    # Processa labels
    labels = [l.strip() for l in labels_text.split(",") if l.strip()] if labels_text else None
    
    # Adiciona informação do criador
    user_id = body["user"]["id"]
    descricao_completa = f"{descricao}\n\n---\nCriado via Slack por <@{user_id}>"
    
    ack()
    
    # Cria a tarefa
    result = jira.criar_tarefa(
        summary=titulo,
        description=descricao_completa,
        issue_type=tipo,
        priority=prioridade,
        labels=labels
    )
    
    # Envia mensagem de confirmação
    if result['success']:
        client.chat_postMessage(
            channel=body["user"]["id"],
            text=f"✅ *Tarefa criada com sucesso!*\n\n"
                 f"*Chave:* {result['key']}\n"
                 f"*Tipo:* {tipo}\n"
                 f"*Prioridade:* {prioridade}\n"
                 f"*Link:* {result['url']}"
        )
    else:
        client.chat_postMessage(
            channel=body["user"]["id"],
            text=f"❌ *Erro ao criar tarefa*\n{result['error']}"
        )

# Menções no canal (@bot criar tarefa...)
@app.event("app_mention")
def handle_mention(event, say):
    """Responde quando o bot é mencionado"""
    text = event['text'].lower()
    
    if 'ajuda' in text or 'help' in text:
        say(
            f"👋 Olá! Eu crio tarefas no Jira automaticamente.\n\n"
            f"*Comandos disponíveis:*\n"
            f"• `/criar-tarefa [título]` - Cria tarefa rápida\n"
            f"• `/nova-tarefa` - Abre formulário completo\n"
            f"• Me mencione com `@bot ajuda` para ver esta mensagem"
        )
    else:
        say("Use `/nova-tarefa` para criar uma tarefa no Jira! 🎯")

if __name__ == "__main__":
    # Cria servidor HTTP simples para o Render detectar
    from flask import Flask
    from threading import Thread
    
    web_app = Flask(__name__)
    
    @web_app.route('/')
    def home():
        return "🤖 Bot Slack está rodando!"
    
    @web_app.route('/health')
    def health():
        return {"status": "ok"}
    
    def run_flask():
        port = int(os.getenv('PORT', 10000))
        web_app.run(host='0.0.0.0', port=port)
    
    # Inicia Flask em thread separada
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Inicia o bot em modo Socket
    handler = SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN"))
    print("⚡ Bot Slack está rodando!")
    handler.start()
