import os
import random
import string
import smtplib
from email.mime.text import MIMEText
from flask import Flask, jsonify, request, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# 1. Initialize Flask with explicit folder path definitions for Render
app = Flask(__name__, 
            template_folder='templates', 
            static_folder='sfx', 
            static_url_path='/sfx')

CORS(app)

# Database Configuration (SQLite for local testing, ready for Render PostgreSQL)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'uno_game.db')}")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Email SMTP Settings - Configure these environment variables on Render
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER', 'your_email@gmail.com')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', 'your_app_password')

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    pfp_index = db.Column(db.Integer, default=1) # 1-4 for avatar choices
    is_verified = db.Column(db.Boolean, default=False)
    verification_code = db.Column(db.String(6), nullable=True)

# Master Memory In-Memory State for active tables
game_state = {
    "deck": [],
    "discard_pile": [],
    "players": [],
    "current_turn": 0,
    "direction": 1,
    "current_color": "",
    "current_value": "",
    "game_over": False,
    "winner": None,
    "status_message": "Awaiting game start..."
}

COLORS = ["blue", "green", "red", "yellow"]
VALUES = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "Skip", "Reverse", "+2"]
WILD_CARDS = ["Wild", "+4"]

def generate_deck():
    deck = []
    for color in COLORS:
        for value in VALUES:
            deck.append({"color": color, "value": value})
            if value != "0":
                deck.append({"color": color, "value": value})
    for wild in WILD_CARDS:
        for _ in range(4):
            deck.append({"color": "wild", "value": wild})
    random.shuffle(deck)
    return deck

def send_verification_email(target_email, code):
    msg = MIMEText(f"Your UNO Game verification security authorization code is: {code}")
    msg['Subject'] = 'Verify your UNO Account'
    msg['From'] = SMTP_USER
    msg['To'] = target_email

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [target_email], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Email error: {e}", flush=True)
        return False

# --- FRONTEND ROUTE ---
@app.route('/')
def serve_index():
    return render_template('index.html')

# --- AUTHENTICATION ENDPOINTS ---
@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json or {}
    if not data.get('username') or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Missing registration details!"}), 400

    if User.query.filter_by(username=data['username']).first() or User.query.filter_by(email=data['email']).first():
        return jsonify({"error": "Username or Email already registered!"}), 400
    
    code = ''.join(random.choices(string.digits, k=6))
    hashed_pw = generate_password_hash(data['password'])
    
    new_user = User(
        username=data['username'],
        email=data['email'],
        password_hash=hashed_pw,
        pfp_index=data.get('pfp_index', 1),
        verification_code=code,
        is_verified=False
    )
    db.session.add(new_user)
    db.session.commit()
    
    # Try sending email
    send_verification_email(data['email'], code)
    
    # Always print code to Render logs so you can copy/paste it without email config working yet
    print(f"\n[DEV DEBUG] Verification code for {data['email']} is: {code}\n", flush=True)
    
    return jsonify({"message": "Registration complete! Code issued to email.", "email": data['email']})

@app.route('/api/auth/verify', methods=['POST'])
def verify():
    data = request.json or {}
    user = User.query.filter_by(email=data.get('email'), verification_code=data.get('code')).first()
    if not user:
        return jsonify({"error": "Invalid verification code!"}), 400
    
    user.is_verified = True
    user.verification_code = None
    db.session.commit()
    return jsonify({"success": True, "username": user.username, "pfp_index": user.pfp_index})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    user = User.query.filter_by(username=data.get('username')).first()
    if not user or not check_password_hash(user.password_hash, data.get('password', '')):
        return jsonify({"error": "Invalid username or password credentials."}), 400
    if not user.is_verified:
        return jsonify({"error": "Account not verified! Check email for your code.", "unverified": True, "email": user.email}), 400
    
    return jsonify({"success": True, "username": user.username, "pfp_index": user.pfp_index})

# --- GAME MECHANICS ENDPOINTS ---
@app.route('/api/start_game', methods=['POST'])
def start_game():
    data = request.json or {}
    username = data.get("username", "You")
    pfp_index = data.get("pfp_index", 1)
    
    game_state["deck"] = generate_deck()
    game_state["discard_pile"] = []
    game_state["current_turn"] = 0
    game_state["direction"] = 1
    game_state["game_over"] = False
    game_state["winner"] = None
    
    game_state["players"] = [
        {"name": username, "is_bot": False, "pfp": pfp_index, "hand": []},
        {"name": "Bot Slayer", "is_bot": True, "pfp": 2, "hand": []},
        {"name": "Bot Retro", "is_bot": True, "pfp": 3, "hand": []},
        {"name": "Bot Glitch", "is_bot": True, "pfp": 4, "hand": []}
    ]
    
    for _ in range(7):
        for p in game_state["players"]:
            p["hand"].append(game_state["deck"].pop())
            
    starter = game_state["deck"].pop()
    while starter["color"] == "wild":
        game_state["deck"].insert(0, starter)
        random.shuffle(game_state["deck"])
        starter = game_state["deck"].pop()
        
    game_state["discard_pile"].append(starter)
    game_state["current_color"] = starter["color"]
    game_state["current_value"] = starter["value"]
    game_state["status_message"] = f"Deck shuffled and dealt! Top discard is {starter['color']} {starter['value']}."
    
    return jsonify(get_clean_state())

def get_clean_state():
    state = game_state.copy()
    visible_players = []
    for idx, p in enumerate(state["players"]):
        visible_players.append({
            "name": p["name"],
            "is_bot": p["is_bot"],
            "pfp": p["pfp"],
            "card_count": len(p["hand"]),
            "hand": p["hand"] if idx == 0 else []
        })
    return {
        "players": visible_players,
        "current_turn": state["current_turn"],
        "direction": state["direction"],
        "current_color": state["current_color"],
        "current_value": state["current_value"],
        "top_discard": state["discard_pile"][-1] if state["discard_pile"] else None,
        "game_over": state["game_over"],
        "winner": state["winner"],
        "status_message": state["status_message"]
    }

def advance_turn():
    num_players = len(game_state["players"])
    game_state["current_turn"] = (game_state["current_turn"] + game_state["direction"]) % num_players

def is_playable(card):
    if card["color"] == "wild" or card["color"] == game_state["current_color"] or card["value"] == game_state["current_value"]:
        return True
    return False

@app.route('/api/play_card', methods=['POST'])
def play_card():
    data = request.json or {}
    player_idx = data.get("player_idx", 0)
    card_idx = data.get("card_idx")
    chosen_color = data.get("chosen_color")
    
    if player_idx != game_state["current_turn"] or game_state["game_over"]:
        return jsonify({"error": "Not your turn!"}), 400
        
    player = game_state["players"][player_idx]
    card = player["hand"][card_idx]
    
    if not is_playable(card):
        return jsonify({"error": "Invalid card choice!"}), 400
        
    player["hand"].pop(card_idx)
    game_state["discard_pile"].append(card)
    game_state["current_value"] = card["value"]
    
    msg = f"{player['name']} played a {card['color']} {card['value']}."
    
    if card["color"] == "wild":
        game_state["current_color"] = chosen_color if chosen_color else random.choice(COLORS)
        msg = f"{player['name']} changed active color to {game_state['current_color']}!"
    else:
        game_state["current_color"] = card["color"]
        
    if len(player["hand"]) == 0:
        game_state["game_over"] = True
        game_state["winner"] = player["name"]
        game_state["status_message"] = f"Game Complete! {player['name']} dominated the match!"
        return jsonify(get_clean_state())

    if card["value"] == "Reverse":
        game_state["direction"] *= -1
        msg += " Order reversed!"
        advance_turn()
    elif card["value"] == "Skip":
        msg += " Next player skipped!"
        advance_turn()
        advance_turn()
    elif card["value"] == "+2":
        advance_turn()
        next_p = game_state["players"][game_state["current_turn"]]
        for _ in range(2):
            if game_state["deck"]: next_p["hand"].append(game_state["deck"].pop())
        msg += f" {next_p['name']} draws 2 cards and skips!"
        advance_turn()
    elif card["value"] == "+4":
        advance_turn()
        next_p = game_state["players"][game_state["current_turn"]]
        for _ in range(4):
            if game_state["deck"]: next_p["hand"].append(game_state["deck"].pop())
        msg += f" {next_p['name']} draws 4 cards and skips!"
        advance_turn()
    else:
        advance_turn()

    game_state["status_message"] = msg
    return jsonify(get_clean_state())

@app.route('/api/draw_card', methods=['POST'])
def draw_card():
    data = request.json or {}
    player_idx = data.get("player_idx", 0)
    if player_idx != game_state["current_turn"] or game_state["game_over"]:
        return jsonify({"error": "Not your turn!"}), 400
        
    player = game_state["players"][player_idx]
    if not game_state["deck"]:
        top = game_state["discard_pile"].pop()
        game_state["deck"] = game_state["discard_pile"]
        random.shuffle(game_state["deck"])
        game_state["discard_pile"] = [top]
        
    drawn = game_state["deck"].pop()
    player["hand"].append(drawn)
    
    if is_playable(drawn):
        game_state["status_message"] = f"{player['name']} drew a playable card!"
    else:
        game_state["status_message"] = f"{player['name']} drew a card and skipped."
        advance_turn()
        
    return jsonify(get_clean_state())

@app.route('/api/ai_turn', methods=['POST'])
def ai_turn():
    current_idx = game_state["current_turn"]
    if current_idx == 0 or game_state["game_over"]:
        return jsonify({"error": "Human turn active."}), 400
        
    bot = game_state["players"][current_idx]
    playable_idx = -1
    for idx, card in enumerate(bot["hand"]):
        if is_playable(card):
            playable_idx = idx
            break
            
    if playable_idx != -1:
        request.json = {"player_idx": current_idx, "card_idx": playable_idx, "chosen_color": random.choice(COLORS)}
        return play_card()
    else:
        request.json = {"player_idx": current_idx}
        return draw_card()

# 3. Dynamic setup block for Gunicorn / Render execution vs Local run
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
