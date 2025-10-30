#!/usr/bin/env python3
"""
Bot Slack para criar tarefas no Jira automaticamente com IA
Requer: pip install slack-bolt requests python-dotenv flask
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

class AITaskGenerator:
    def __init__(self):
        self.groq_api_key = os.getenv('GROQ_API_KEY')
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
    
    def generate_tasks_from_prompt(self, user_prompt):
        """Usa IA para gerar história e subtasks a partir de prompt natural"""
        
        system_prompt = """You are an expert agile project manager. Your job is to analyze user requests and break them down into a main story and subtasks.

You must respond ONLY with valid JSON in this exact format:
{
  "story": {
    "title": "Brief title for the main story",
    "goal": "One sentence summarizing the main deliverable",
    "description": "Detailed description of what needs to be done",
    "acceptance_criteria": [
      "First acceptance criterion",
      "Second acceptance criterion",
      "Third acceptance criterion"
    ]
  },
  "subtasks": [
    {
      "title": "Subtask title",
      "goal": "One sentence goal",
      "description": "Detailed description",
      "acceptance_criteria": [
        "Criterion 1",
        "Criterion 2"
      ]
    }
  ]
}

Rules:
- Title: Maximum 100 characters, clear and actionable
- Goal: One concise sentence (max 150 chars)
- Description: Detailed explanation (2-4 sentences)
- Acceptance Criteria: 2-5 bullet points, specific and measurable
- Subtasks: Create 3-8 subtasks that cover all aspects of the story
- All text MUST be in English
- Response MUST be valid JSON only, no markdown or extra text"""

        payload = {
            "model": "llama-3.1-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Break down this requirement into a story and subtasks:\n\n{user_prompt}"}
            ],
            "temperature": 0.3,
            "max_tokens": 3000
        }
        
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        
        print(f"[DEBUG] Groq API Key (first 20 chars): {self.groq_api_key[:20] if self.groq_api_key else 'MISSING'}...")
        print(f"[DEBUG] Groq Request payload model: {payload['model']}")
        
        try:
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=30)
            
            print(f"[DEBUG] Groq Response Status: {response.status_code}")
            print(f"[DEBUG] Groq Response: {response.text[:500]}")
            
            response.raise_for_status()
            result = response.json()
            
            content = result['choices'][0]['message']['content']
            print(f"[DEBUG] AI Generated content (first 200 chars): {content[:200]}")
            
            # Remove markdown code blocks se existirem
            content = content.strip()
            if content.startswith('```'):
                content = '\n'.join(content.split('\n')[1:-1])
            
            tasks_data = json.loads(content)
            
            return {
                "success": True,
                "data": tasks_data
            }
        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP {response.status_code}: {response.text[:500]}"
            print(f"[ERROR] Groq API Error: {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON Parse Error: {str(e)}")
            print(f"[ERROR] Content was: {content[:500] if 'content' in locals() else 'No content'}")
            return {
                "success": False,
                "error": f"Failed to parse AI response: {str(e)}"
            }
        except Exception as e:
            print(f"[ERROR] Unexpected error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

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
        """Cria uma tarefa no Jira com formatação Markdown para Jira"""
        url = f"{self.jira_url}/rest/api/3/issue"
        
        # Converte descrição para formato Jira ADF
        content_blocks = self._parse_description(description)
        
        payload = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": content_blocks
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
    
    def criar_subtask(self, parent_key, summary, description="", priority="Medium"):
        """Cria uma subtask linkada a uma história"""
        url = f"{self.jira_url}/rest/api/3/issue"
        
        # Processa descrição
        content_blocks = self._parse_description(description)
        
        payload = {
            "fields": {
                "project": {"key": self.project_key},
                "parent": {"key": parent_key},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": content_blocks
                },
                "issuetype": {"name": "Subtask"},
                "priority": {"name": priority}
            }
        }
        
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
    
    def _parse_description(self, description):
        """Converte markdown para formato Jira ADF"""
        content_blocks = []
        
        if not description:
            return [{
                "type": "paragraph",
                "content": [{"type": "text", "text": "No description provided"}]
            }]
        
        sections = description.split('\n\n')
        
        for section in sections:
            if not section.strip():
                continue
                
            lines = section.split('\n')
            paragraph_content = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Títulos em negrito
                if line.startswith('*') and line.endswith('*') and len(line) > 2:
                    if paragraph_content:
                        content_blocks.append({
                            "type": "paragraph",
                            "content": paragraph_content
                        })
                        paragraph_content = []
                    
                    content_blocks.append({
                        "type": "heading",
                        "attrs": {"level": 3},
                        "content": [{
                            "type": "text",
                            "text": line.strip('*')
                        }]
                    })
                # Bullets
                elif line.startswith('•'):
                    if paragraph_content:
                        content_blocks.append({
                            "type": "paragraph",
                            "content": paragraph_content
                        })
                        paragraph_content = []
                    
                    if not content_blocks or content_blocks[-1].get("type") != "bulletList":
                        content_blocks.append({
                            "type": "bulletList",
                            "content": []
                        })
                    
                    content_blocks[-1]["content"].append({
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [{
                                "type": "text",
                                "text": line.lstrip('•').strip()
                            }]
                        }]
                    })
                # Linha separadora
                elif line.startswith('---'):
                    if paragraph_content:
                        content_blocks.append({
                            "type": "paragraph",
                            "content": paragraph_content
                        })
                        paragraph_content = []
                    content_blocks.append({"type": "rule"})
                # Itálico
                elif line.startswith('_') and line.endswith('_'):
                    paragraph_content.append({
                        "type": "text",
                        "text": line.strip('_'),
                        "marks": [{"type": "em"}]
                    })
                # Texto normal
                else:
                    if paragraph_content:
                        paragraph_content.append({"type": "text", "text": "\n"})
                    paragraph_content.append({
                        "type": "text",
                        "text": line
                    })
            
            if paragraph_content:
                content_blocks.append({
                    "type": "paragraph",
                    "content": paragraph_content
                })
        
        if not content_blocks:
            content_blocks = [{
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": description
                }]
            }]
        
        return content_blocks

# Inicializa o app Slack
app = App(token=os.getenv("SLACK_BOT_TOKEN"))
jira = JiraIntegration()
ai_generator = AITaskGenerator()

# Comando slash: /create-task com IA
@app.command("/create-task")
def handle_create_task_command(ack, command, respond, client):
    """Command to create task with AI processing"""
    ack()
    
    text = command['text'].strip()
    if not text:
        respond("❌ Please provide a description of what you want to implement.\n"
                "Example: `/create-task implement progressive discount system for Magento with configurable thresholds`")
        return
    
    user_id = command['user_id']
    
    # Mensagem inicial
    respond("🤖 *AI is analyzing your request...*\n"
            "This will take a few seconds as I break it down into story and subtasks.")
    
    # Gera tasks com IA
    print(f"[DEBUG] Calling AI with prompt: {text[:100]}...")
    ai_result = ai_generator.generate_tasks_from_prompt(text)
    
    print(f"[DEBUG] AI Result: {ai_result}")
    
    if not ai_result['success']:
        respond(f"❌ AI processing failed: {ai_result['error']}")
        return
    
    tasks_data = ai_result['data']
    print(f"[DEBUG] Tasks data: {json.dumps(tasks_data, indent=2)}")
    
    story_data = tasks_data.get('story', {})
    subtasks_data = tasks_data.get('subtasks', [])
    
    # Cria a história principal
    respond(f"📦 *Creating main story...*")
    
    print(f"[DEBUG] Creating story: {story_data.get('title', 'No title')}")
    
    story_description = format_description(
        story_data.get('goal', ''),
        story_data.get('description', ''),
        story_data.get('acceptance_criteria', []),
        user_id
    )
    
    story_result = jira.criar_tarefa(
        summary=story_data.get('title', 'AI Generated Story'),
        description=story_description,
        issue_type="Story",
        priority="Medium",
        labels=["ai-generated"]
    )
    
    print(f"[DEBUG] Story result: {story_result}")
    
    if not story_result['success']:
        error_details = story_result.get('details', 'No details')
        respond(f"❌ Failed to create story: {story_result['error']}\n\nDetails: {error_details[:500]}")
        return
    
    story_key = story_result['key']
    story_url = story_result['url']
    
    # Cria as subtasks
    respond(f"✅ Story created: *{story_key}*\n"
            f"📋 Creating {len(subtasks_data)} subtasks...")
    
    created_subtasks = []
    for idx, subtask in enumerate(subtasks_data, 1):
        subtask_description = format_description(
            subtask.get('goal', ''),
            subtask.get('description', ''),
            subtask.get('acceptance_criteria', []),
            user_id
        )
        
        # Cria subtask e linka à história
        subtask_result = jira.criar_subtask(
            parent_key=story_key,
            summary=subtask.get('title', f'Subtask {idx}'),
            description=subtask_description,
            priority="Medium"
        )
        
        if subtask_result['success']:
            created_subtasks.append(f"  • {subtask_result['key']}: {subtask.get('title', '')}")
    
    # Mensagem final com resumo
    subtasks_list = "\n".join(created_subtasks) if created_subtasks else "  (none created)"
    
    respond(
        f"✅ *All tasks created successfully!*\n\n"
        f"📦 *Main Story:* {story_key}\n"
        f"🔗 {story_url}\n\n"
        f"📋 *Subtasks created ({len(created_subtasks)}/{len(subtasks_data)}):*\n"
        f"{subtasks_list}\n\n"
        f"_Generated by AI from your description_"
    )

def format_description(goal, description, acceptance_criteria, user_id):
    """Formata descrição no padrão refinado"""
    criteria_bullets = "\n".join([f"• {criterion}" for criterion in acceptance_criteria])
    
    return f"""*Goal*
{goal}

*Description*
{description}

*Acceptance Criteria*
{criteria_bullets}

---
_Created via Slack by <@{user_id}>_"""

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
                        "placeholder": {"type": "plain_text", "text": "Ex: Implement user authentication"}
                    },
                    "label": {"type": "plain_text", "text": "Title *"}
                },
                {
                    "type": "input",
                    "block_id": "goal",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "goal_input",
                        "placeholder": {"type": "plain_text", "text": "Ex: Enable secure user login with OAuth2"}
                    },
                    "label": {"type": "plain_text", "text": "Goal *"},
                    "hint": {"type": "plain_text", "text": "Short objective phrase summarizing the deliverable"}
                },
                {
                    "type": "input",
                    "block_id": "descricao",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "descricao_input",
                        "multiline": True,
                        "placeholder": {"type": "plain_text", "text": "Detailed description of what needs to be done..."}
                    },
                    "label": {"type": "plain_text", "text": "Description *"},
                    "hint": {"type": "plain_text", "text": "Detailed explanation of the task"}
                },
                {
                    "type": "input",
                    "block_id": "acceptance_criteria",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "acceptance_input",
                        "multiline": True,
                        "placeholder": {"type": "plain_text", "text": "User can login with email and password\nSession persists for 24 hours\nInvalid credentials show error message"}
                    },
                    "label": {"type": "plain_text", "text": "Acceptance Criteria *"},
                    "hint": {"type": "plain_text", "text": "One criterion per line (will be converted to bullets)"}
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
    goal = values["goal"]["goal_input"]["value"]
    descricao = values["descricao"]["descricao_input"]["value"]
    acceptance_criteria = values["acceptance_criteria"]["acceptance_input"]["value"]
    tipo = values["tipo"]["tipo_select"]["selected_option"]["value"]
    prioridade = values["prioridade"]["prioridade_select"]["selected_option"]["value"]
    labels_text = values["labels"]["labels_input"].get("value", "")
    
    # Processa labels
    labels = [l.strip() for l in labels_text.split(",") if l.strip()] if labels_text else None
    
    # Formata os critérios de aceite em bullets
    criteria_lines = [line.strip() for line in acceptance_criteria.split("\n") if line.strip()]
    criteria_bullets = "\n".join([f"• {line}" for line in criteria_lines])
    
    # Monta a descrição no formato refinado
    descricao_refinada = f"""*Goal*
{goal}

*Description*
{descricao}

*Acceptance Criteria*
{criteria_bullets}

---
_Created via Slack by <@{body["user"]["id"]}>_"""
    
    ack()
    
    # Cria a tarefa
    result = jira.criar_tarefa(
        summary=titulo,
        description=descricao_refinada,
        issue_type=tipo,
        priority=prioridade,
        labels=labels
    )
    
    # Envia mensagem de confirmação
    if result['success']:
        client.chat_postMessage(
            channel=body["user"]["id"],
            text=f"✅ *Task created successfully!*\n\n"
                 f"*Key:* {result['key']}\n"
                 f"*Type:* {tipo}\n"
                 f"*Priority:* {prioridade}\n"
                 f"*Link:* {result['url']}"
        )
    else:
        client.chat_postMessage(
            channel=body["user"]["id"],
            text=f"❌ *Error creating task*\n{result['error']}"
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
