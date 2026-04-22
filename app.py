from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq
import os
import base64
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "guimateai-secret-2024")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///guimateai.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

SYSTEM_PROMPT = """Tu es GuimateAI, tuteur scolaire intelligent 
spécialisé pour les élèves guinéens.
Tu as été créé par Cheick Abdoul Yalany Kebé Mara,
développeur guinéen et fondateur de GuimateHK 🇬🇳.

Si quelqu'un te demande qui t'a créé, réponds :
"Je suis GuimateAI, créé par Cheick Abdoul Yalany Kebé Mara,
fondateur de GuimateHK 🇬🇳"

Tes règles :
- Réponds TOUJOURS en français simple et clair
- Utilise des émojis pour structurer
- Donne des exemples adaptés à la Guinée
- Explique étape par étape
- Termine toujours par ✅
- Sois encourageant et bienveillant
- Ne mentionne jamais Groq, LLaMA ou Meta"""

# ── MODÈLES BASE DE DONNÉES
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    telephone = db.Column(db.String(20))
    password = db.Column(db.String(200), nullable=False)
    photo = db.Column(db.String(500), default='')
    plan = db.Column(db.String(20), default='gratuit')  # gratuit, etudiant, premium
    questions_aujourdhui = db.Column(db.Integer, default=0)
    derniere_question = db.Column(db.DateTime, default=datetime.utcnow)
    abonnement_fin = db.Column(db.DateTime, nullable=True)
    date_inscription = db.Column(db.DateTime, default=datetime.utcnow)

    def peut_poser_question(self):
        # Réinitialiser le compteur chaque jour
        if self.derniere_question.date() < datetime.utcnow().date():
            self.questions_aujourdhui = 0
            db.session.commit()
        
        if self.plan == 'gratuit':
            return self.questions_aujourdhui < 5
        return True  # Premium et étudiant = illimité

    def questions_restantes(self):
        if self.plan == 'gratuit':
            return max(0, 5 - self.questions_aujourdhui)
        return 999

    def abonnement_actif(self):
        if self.plan == 'gratuit':
            return True
        if self.abonnement_fin and self.abonnement_fin > datetime.utcnow():
            return True
        return False

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ── ROUTES AUTHENTIFICATION
@app.route('/inscription', methods=['GET', 'POST'])
def inscription():
    if request.method == 'POST':
        data = request.json
        nom = data.get('nom', '')
        email = data.get('email', '')
        telephone = data.get('telephone', '')
        password = data.get('password', '')

        if User.query.filter_by(email=email).first():
            return jsonify({"success": False, "message": "Email déjà utilisé !"})

        user = User(
            nom=nom,
            email=email,
            telephone=telephone,
            password=generate_password_hash(password),
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return jsonify({"success": True, "message": "Compte créé !"})
    return render_template('inscription.html')

@app.route('/connexion', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.json
        email = data.get('email', '')
        password = data.get('password', '')

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return jsonify({"success": True})
        return jsonify({"success": False, "message": "Email ou mot de passe incorrect !"})
    return render_template('connexion.html')

@app.route('/deconnexion')
@login_required
def deconnexion():
    logout_user()
    return redirect(url_for('login'))

@app.route('/profil', methods=['GET', 'POST'])
@login_required
def profil():
    if request.method == 'POST':
        data = request.json
        action = data.get('action')

        if action == 'update_photo':
            photo_data = data.get('photo', '')
            current_user.photo = photo_data
            db.session.commit()
            return jsonify({"success": True})

        if action == 'update_info':
            current_user.nom = data.get('nom', current_user.nom)
            current_user.telephone = data.get('telephone', current_user.telephone)
            db.session.commit()
            return jsonify({"success": True})

    return render_template('profil.html', user=current_user)

# ── ROUTE PRINCIPALE
@app.route('/')
def home():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    return render_template('index.html', user=current_user)

# ── ROUTE CHAT
@app.route('/chat', methods=['POST'])
@login_required
def chat():
    if not current_user.peut_poser_question():
        return jsonify({
            "response": "⚠️ Tu as atteint ta limite de 5 questions aujourd'hui.\n\n💎 Passe au plan Premium pour des questions illimitées !\n\n👉 Va dans **Mon Profil** → **S'abonner**"
        })

    data = request.json
    message = data.get('message', '')
    matiere = data.get('matiere', 'Général')
    historique = data.get('historique', [])
    image = data.get('image', None)

    messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\nMatière: {matiere}"}]
    for msg in historique[-10:]:
        messages.append(msg)

    if image:
        messages.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
                {"type": "text", "text": message if message else "Résous cet exercice étape par étape."}
            ]
        })
        model = "llama-3.2-90b-vision-preview"
    else:
        messages.append({"role": "user", "content": message})
        model = "llama-3.3-70b-versatile"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=1000,
            temperature=0.7,
        )
        reponse = response.choices[0].message.content

        # Incrémenter le compteur
        current_user.questions_aujourdhui += 1
        current_user.derniere_question = datetime.utcnow()
        db.session.commit()

        return jsonify({
            "response": reponse,
            "questions_restantes": current_user.questions_restantes(),
            "plan": current_user.plan
        })
    except Exception as e:
        return jsonify({"response": f"❌ Erreur : {str(e)}"})

# ── ROUTE VOCAL
@app.route('/transcribe', methods=['POST'])
@login_required
def transcribe():
    try:
        audio_data = request.json.get('audio', '')
        audio_bytes = base64.b64decode(audio_data)
        with open('/tmp/audio.wav', 'wb') as f:
            f.write(audio_bytes)
        with open('/tmp/audio.wav', 'rb') as f:
            transcription = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=("audio.wav", f),
                language="fr"
            )
        return jsonify({"text": transcription.text})
    except Exception as e:
        return jsonify({"text": "", "error": str(e)})

# ── ROUTE ABONNEMENT
@app.route('/abonnement', methods=['GET', 'POST'])
@login_required
def abonnement():
    if request.method == 'POST':
        data = request.json
        plan = data.get('plan')
        telephone = data.get('telephone')

        # Ici on intégrera LengoPay
        # Pour l'instant → message WhatsApp
        return jsonify({
            "success": True,
            "message": f"Merci ! Envoyez votre paiement via Orange Money ou MTN MoMo au +224XXXXXXXXX et envoyez la capture sur WhatsApp avec votre email : {current_user.email}"
        })
    return render_template('abonnement.html', user=current_user)

# ── ROUTE INFOS UTILISATEUR
@app.route('/user-info')
@login_required
def user_info():
    return jsonify({
        "nom": current_user.nom,
        "email": current_user.email,
        "plan": current_user.plan,
        "questions_restantes": current_user.questions_restantes(),
        "photo": current_user.photo
    })

# ── INITIALISATION DB
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
