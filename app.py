from flask import Flask, render_template, request, jsonify, session
from groq import Groq
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

SYSTEM_PROMPT = """Tu es GuimateAI, tuteur scolaire intelligent 
spécialisé pour les élèves guinéens. Tu as été créé par Cheick, 
développeur guinéen et fondateur de GuimateHK.
- Réponds en français simple avec émojis
- Exemples adaptés à la Guinée
- Explique étape par étape
- Termine par ✅"""

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    message = data.get('message', '')
    matiere = data.get('matiere', 'Général')
    historique = data.get('historique', [])
    
    messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\nMatière: {matiere}"}]
    for msg in historique[-10:]:
        messages.append(msg)
    messages.append({"role": "user", "content": message})
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=800,
        temperature=0.7,
    )
    
    return jsonify({"response": response.choices[0].message.content})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
