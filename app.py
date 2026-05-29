import os
import random
import string
import base64
from flask import Flask, jsonify, request, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

# Initialize Flask with explicit folder path definitions for Render
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

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    is_owner = db.Column(db.Boolean, default=False)
    avatar_source = db.Column(db.Text, default="1")

# Master In-Memory State for active tables
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

# --- FRONTEND ROUTE ---
@app.route('/')
def serve_index():
    return render_template('index.html')

# --- GAME JOIN / SETUP ENDPOINT ---
@app.route('/api/start_game', methods=['POST'])
def start_game():
    data = request.json or {}
    
    username = data.get("username", "").strip()
    if not username:
        username = f"Guest_{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"
        
    # Check if this player is the hardcoded owner
    player_email = data.get("email", "").strip().lower()
    is_owner_profile = (player_email == "whyiseliashere@gmail.com")

    # If avatar_source is provided (uploaded custom image), use it.
    # Otherwise, assign a completely random sample index from 1 to 4.
    avatar_source = data.get("avatar_source")
    if not avatar_source:
        avatar_source = str(random.randint(1, 4))
    
    game_state["deck"] = generate_deck()
    game_state["discard_pile"] = []
    game_state["current_turn"] = 0
    game_state["direction"] = 1
    game_state["game_over"] = False
    game_state["winner"] = None
    
    # Configure match entities
    game_state["players"] = [
        {"name": username, "is_bot": False, "avatar": avatar_source, "is_owner": is_owner_profile, "hand": []},
        {"name": "Bot Slayer", "is_bot": True, "avatar": "2", "is_owner": False, "hand": []},
        {"name": "Bot Retro", "is_bot": True, "avatar": "3", "is_owner": False, "hand": []},
        {"name": "Bot Glitch", "is_bot": True, "avatar": "4", "is_owner": False, "hand": []}
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
    game_state["status_message"] = f"Match initialized! Top discard is {starter['color']} {starter['value']}."
    
    return jsonify(get_clean_state())

def get_clean_state():
    state = game_state.copy()
    visible_players = []
    for idx, p in enumerate(state["players"]):
        visible_players.append({
            "name": p["name"],
            "is_bot": p["is_bot"],
            "avatar": p["avatar"],
            "is_owner": p.get("is_owner", False),
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
    if card_idx is None or card_idx >= len(player["hand"]):
        return jsonify({"error": "Invalid card index!"}), 400
        
    card = player["hand"][card_idx]
    
    if not is_playable(card):
        return jsonify({"error": "Invalid card choice!"}), 400
        
    player["hand"].pop(card_idx)
    game_state["discard_pile"].append(card)
    game_state["current_value"] = card["value"]
    
    msg = f"{player['name']} played a {card['color']} {card['value']}."
    
    if card["color"] == "wild":
        game_state["current_color"] = chosen_color if chosen_color in COLORS else random.choice(COLORS)
        msg = f"{player['name']} played a Wild and changed active color to {game_state['current_color']}!"
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
        if len(game_state["discard_pile"]) > 1:
            top = game_state["discard_pile"].pop()
            game_state["deck"] = game_state["discard_pile"]
            random.shuffle(game_state["deck"])
            game_state["discard_pile"] = [top]
        else:
            game_state["deck"] = generate_deck()
        
    drawn = game_state["deck"].pop()
    player["hand"].append(drawn)
    
    if is_playable(drawn):
        game_state["status_message"] = f"{player['name']} drew a card and it can be played!"
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
        # Simulate local modifications to internal endpoint values cleanly
        card = bot["hand"][playable_idx]
        chosen_color = random.choice(COLORS)
        bot["hand"].pop(playable_idx)
        game_state["discard_pile"].append(card)
        game_state["current_value"] = card["value"]
        msg = f"{bot['name']} played a {card['color']} {card['value']}."
        
        if card["color"] == "wild":
            game_state["current_color"] = chosen_color
            msg = f"{bot['name']} played a Wild and changed active color to {chosen_color}!"
        else:
            game_state["current_color"] = card["color"]
            
        if len(bot["hand"]) == 0:
            game_state["game_over"] = True
            game_state["winner"] = bot["name"]
            game_state["status_message"] = f"Game Complete! {bot['name']} dominated the match!"
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
    else:
        if not game_state["deck"]:
            if len(game_state["discard_pile"]) > 1:
                top = game_state["discard_pile"].pop()
                game_state["deck"] = game_state["discard_pile"]
                random.shuffle(game_state["deck"])
                game_state["discard_pile"] = [top]
            else:
                game_state["deck"] = generate_deck()
                
        drawn = game_state["deck"].pop()
        bot["hand"].append(drawn)
        
        if is_playable(drawn):
            # Play immediately if bot draws a valid option
            card_idx = len(bot["hand"]) - 1
            card = bot["hand"].pop(card_idx)
            game_state["discard_pile"].append(card)
            game_state["current_value"] = card["value"]
            msg = f"{bot['name']} drew and played a {card['color']} {card['value']}."
            if card["color"] == "wild":
                game_state["current_color"] = random.choice(COLORS)
            else:
                game_state["current_color"] = card["color"]
            advance_turn()
            game_state["status_message"] = msg
        else:
            game_state["status_message"] = f"{bot['name']} drew a card and skipped."
            advance_turn()
            
        return jsonify(get_clean_state())

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
