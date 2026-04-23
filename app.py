from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq
import os
import base64
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "guimateai-2024")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///guimateai.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

SYSTEM_PROMPT = """Tu es GuimateAI, tuteur scolaire intelligent specialise pour les eleves guineens.
Tu as ete cree par Cheick Abdoul Yalany Kebe Mara, developpeur guineen et fondateur de GuimateHK.
Si quelqu'un te demande qui t'a cree : Je suis GuimateAI, cree par Cheick Abdoul Yalany Kebe Mara, fondateur de GuimateHK.
Regles : Reponds en francais simple avec emojis. Exemples adaptes a la Guinee. Explique etape par etape. Termine par OK. Ne mentionne jamais Groq, LLaMA ou Meta."""

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    telephone = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    photo = db.Column(db.Text, default='')
    plan = db.Column(db.String(20), default='gratuit')
    questions_aujourdhui = db.Column(db.Integer, default=0)
    derniere_question = db.Column(db.DateTime, default=datetime.utcnow)
    note = db.Column(db.Integer, default=0)
    date_inscription = db.Column(db.DateTime, default=datetime.utcnow)

    def peut_poser_question(self):
        if self.derniere_question.date() < datetime.utcnow().date():
            self.questions_aujourdhui = 0
            db.session.commit()
        if self.plan == 'gratuit':
            return self.questions_aujourdhui < 15
        return True

    def questions_restantes(self):
        if self.plan == 'gratuit':
            return max(0, 15 - self.questions_aujourdhui)
        return 999

class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    titre = db.Column(db.String(200), default='Nouvelle conversation')
    matiere = db.Column(db.String(50), default='General')
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_modification = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship('Message', backref='conversation', lazy=True, cascade='all, delete-orphan')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    role = db.Column(db.String(20))
    contenu = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    note = db.Column(db.Integer)
    commentaire = db.Column(db.Text, default='')
    date = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/inscription', methods=['GET', 'POST'])
def inscription():
    if request.method == 'POST':
        data = request.json
        nom = data.get('nom', '')
        telephone = data.get('telephone', '')
        password = data.get('password', '')
        if User.query.filter_by(telephone=telephone).first():
            return jsonify({"success": False, "message": "Numero deja utilise !"})
        user = User(nom=nom, telephone=telephone, password=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return jsonify({"success": True})
    return render_template('inscription.html')

@app.route('/connexion', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.json
        telephone = data.get('telephone', '')
        password = data.get('password', '')
        user = User.query.filter_by(telephone=telephone).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return jsonify({"success": True})
        return jsonify({"success": False, "message": "Numero ou mot de passe incorrect !"})
    return render_template('connexion.html')

@app.route('/deconnexion')
@login_required
def deconnexion():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
def home():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    return render_template('index.html', user=current_user)

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    if not current_user.peut_poser_question():
        return jsonify({"response": "Tu as atteint ta limite de 15 questions aujourd'hui. Passe Premium pour des questions illimitees !", "limite_atteinte": True})
    data = request.json
    message = data.get('message', '')
    matiere = data.get('matiere', 'General')
    historique = data.get('historique', [])
    image = data.get('image', None)
    conversation_id = data.get('conversation_id', None)

    if conversation_id:
        conv = Conversation.query.get(conversation_id)
    else:
        conv = Conversation(user_id=current_user.id, titre=message[:50] if message else 'Conversation', matiere=matiere)
        db.session.add(conv)
        db.session.flush()

    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\nMatiere: " + matiere}]
    for msg in historique[-10:]:
        messages.append(msg)

    if image:
        messages.append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image}}, {"type": "text", "text": message if message else "Resous cet exercice etape par etape."}]})
        model = "llama-3.2-90b-vision-preview"
    else:
        messages.append({"role": "user", "content": message})
        model = "llama-3.3-70b-versatile"

    try:
        response = client.chat.completions.create(model=model, messages=messages, max_tokens=1000, temperature=0.7)
        reponse = response.choices[0].message.content
        db.session.add(Message(conversation_id=conv.id, user_id=current_user.id, role='user', contenu=message))
        db.session.add(Message(conversation_id=conv.id, user_id=current_user.id, role='assistant', contenu=reponse))
        conv.date_modification = datetime.utcnow()
        current_user.questions_aujourdhui += 1
        current_user.derniere_question = datetime.utcnow()
        db.session.commit()
        return jsonify({"response": reponse, "questions_restantes": current_user.questions_restantes(), "plan": current_user.plan, "conversation_id": conv.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"response": "Erreur : " + str(e)})

@app.route('/historique', methods=['GET'])
@login_required
def historique():
    conversations = Conversation.query.filter_by(user_id=current_user.id).order_by(Conversation.date_modification.desc()).all()
    result = []
    for conv in conversations:
        result.append({"id": conv.id, "titre": conv.titre, "matiere": conv.matiere, "date": conv.date_modification.strftime("%d/%m/%Y %H:%M"), "nb_messages": len(conv.messages)})
    return jsonify(result)

@app.route('/conversation/<int:conv_id>', methods=['GET'])
@login_required
def get_conversation(conv_id):
    conv = Conversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
    if not conv:
        return jsonify({"error": "Introuvable"}), 404
    messages = [{"role": msg.role, "contenu": msg.contenu, "date": msg.date.strftime("%H:%M")} for msg in conv.messages]
    return jsonify({"id": conv.id, "titre": conv.titre, "matiere": conv.matiere, "messages": messages})

@app.route('/conversation/<int:conv_id>/supprimer', methods=['POST'])
@login_required
def supprimer_conversation(conv_id):
    conv = Conversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
    if conv:
        db.session.delete(conv)
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/supprimer-historique', methods=['POST'])
@login_required
def supprimer_historique():
    Conversation.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"success": True})

@app.route('/profil', methods=['GET', 'POST'])
@login_required
def profil():
    if request.method == 'POST':
        data = request.json
        action = data.get('action')
        if action == 'update_photo':
            current_user.photo = data.get('photo', '')
            db.session.commit()
            return jsonify({"success": True, "message": "Photo mise a jour !"})
        if action == 'update_info':
            current_user.nom = data.get('nom', current_user.nom)
            current_user.telephone = data.get('telephone', current_user.telephone)
            db.session.commit()
            return jsonify({"success": True, "message": "Profil mis a jour !"})
        if action == 'change_password':
            ancien = data.get('ancien_password', '')
            nouveau = data.get('nouveau_password', '')
            if check_password_hash(current_user.password, ancien):
                current_user.password = generate_password_hash(nouveau)
                db.session.commit()
                return jsonify({"success": True, "message": "Mot de passe change !"})
            return jsonify({"success": False, "message": "Ancien mot de passe incorrect !"})
    return render_template('profil.html', user=current_user)

@app.route('/noter', methods=['POST'])
@login_required
def noter():
    data = request.json
    note = data.get('note', 0)
    commentaire = data.get('commentaire', '')
    Note.query.filter_by(user_id=current_user.id).delete()
    db.session.add(Note(user_id=current_user.id, note=note, commentaire=commentaire))
    current_user.note = note
    db.session.commit()
    return jsonify({"success": True, "message": "Merci pour ta note !"})

@app.route('/transcribe', methods=['POST'])
@login_required
def transcribe():
    try:
        audio_data = request.json.get('audio', '')
        audio_bytes = base64.b64decode(audio_data)
        with open('/tmp/audio.wav', 'wb') as f:
            f.write(audio_bytes)
        with open('/tmp/audio.wav', 'rb') as f:
            transcription = client.audio.transcriptions.create(model="whisper-large-v3", file=("audio.wav", f), language="fr")
        return jsonify({"text": transcription.text})
    except Exception as e:
        return jsonify({"text": "", "error": str(e)})

@app.route('/abonnement', methods=['POST'])
@login_required
def abonnement():
    data = request.json
    plan = data.get('plan')
    prix = {"etudiant": "5 000", "premium": "15 000"}.get(plan, "0")
    return jsonify({"success": True, "message": "Pour activer le plan " + plan + ", envoyez " + prix + " GNF via Orange Money ou MTN MoMo. Contactez-nous sur WhatsApp avec votre numero de telephone."})

@app.route('/user-info')
@login_required
def user_info():
    return jsonify({"nom": current_user.nom, "telephone": current_user.telephone, "plan": current_user.plan, "questions_restantes": current_user.questions_restantes(), "photo": current_user.photo, "note": current_user.note})

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
