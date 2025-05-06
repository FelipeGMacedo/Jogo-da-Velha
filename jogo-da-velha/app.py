from flask import Flask, render_template
from flask_socketio import SocketIO, emit, disconnect, join_room, leave_room
from flask import request
import os
import uuid
import logging
import random

app = Flask(__name__)
app.config["SECRET_KEY"] = "secret!"
socketio = SocketIO(app)

# Configura logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Dicionário para estados de todas as salas (multiplayer e bot)
game_states = {}

def get_or_create_room(room_id=None, force_new=False):
    """Retorna uma sala multiplayer existente com menos de 2 jogadores ou cria uma nova."""
    logger.debug(f"Procurando sala para room_id: {room_id}, force_new: {force_new}")
    if not force_new:
        if room_id and room_id in game_states and len(game_states[room_id]["players"]) < 2 and not room_id.startswith("bot_"):
            logger.debug(f"Entrando na sala existente: {room_id}")
            return room_id
        for rid, state in game_states.items():
            if len(state["players"]) < 2 and not rid.startswith("bot_"):
                logger.debug(f"Entrando na sala disponível: {rid}")
                return rid
    new_room_id = str(uuid.uuid4())[:8]
    game_states[new_room_id] = {
        "board": [["" for _ in range(3)] for _ in range(3)],
        "current_player": "X",
        "winner": None,
        "game_over": False,
        "scoreboard": {"Draw": 0},
        "players": {},
        "is_bot_game": False
    }
    logger.debug(f"Criada nova sala multiplayer: {new_room_id}")
    return new_room_id

def get_available_rooms():
    """Retorna a lista de salas multiplayer com menos de 2 jogadores."""
    return [room_id for room_id, state in game_states.items() if len(state["players"]) < 2 and not room_id.startswith("bot_")]

def check_winner(board):
    for row in board:
        if row[0] == row[1] == row[2] != "":
            return row[0]
    for col in range(3):
        if board[0][col] == board[1][col] == board[2][col] != "":
            return board[0][col]
    if board[0][0] == board[1][1] == board[2][2] != "":
        return board[0][0]
    if board[0][2] == board[1][1] == board[2][0] != "":
        return board[0][2]
    if all(cell != "" for row in board for cell in row):
        return "Draw"
    return None

def get_player_names(room_id):
    """Retorna os nomes dos jogadores na sala."""
    state = game_states.get(room_id, {"players": {}})
    player_x_name = None
    player_o_name = None
    for sid, info in state["players"].items():
        if info["role"] == "X":
            player_x_name = info["name"]
        elif info["role"] == "O":
            player_o_name = info["name"]
    return player_x_name, player_o_name

def bot_make_move(room_id):
    """Lógica do bot para fazer uma jogada como O."""
    state = game_states[room_id]
    board = state["board"]
    logger.debug(f"Bot fazendo jogada na sala {room_id}")

    # Função auxiliar para verificar se uma jogada vence
    def can_win(player, row, col):
        temp = board[row][col]
        board[row][col] = player
        winner = check_winner(board)
        board[row][col] = temp
        return winner == player

    # 1. Jogar para vencer (O)
    for i in range(3):
        for j in range(3):
            if board[i][j] == "":
                if can_win("O", i, j):
                    board[i][j] = "O"
                    logger.debug(f"Bot jogou em ({i}, {j}) para vencer")
                    return i, j

    # 2. Bloquear vitória do jogador (X)
    for i in range(3):
        for j in range(3):
            if board[i][j] == "":
                if can_win("X", i, j):
                    board[i][j] = "O"
                    logger.debug(f"Bot jogou em ({i}, {j}) para bloquear X")
                    return i, j

    # 3. Jogar aleatoriamente
    empty_cells = [(i, j) for i in range(3) for j in range(3) if board[i][j] == ""]
    if empty_cells:
        i, j = random.choice(empty_cells)
        board[i][j] = "O"
        logger.debug(f"Bot jogou aleatoriamente em ({i}, {j})")
        return i, j

    logger.warning(f"Bot não encontrou jogadas válidas na sala {room_id}")
    return None

@app.route("/")
def index():
    return render_template("index.html")

@socketio.on("connect")
def handle_connect():
    logger.debug(f"Novo cliente conectado: {request.sid}")
    emit("update_rooms", {"rooms": get_available_rooms()})

@socketio.on("get_rooms")
def handle_get_rooms():
    logger.debug(f"Cliente {request.sid} solicitou lista de salas")
    emit("update_rooms", {"rooms": get_available_rooms()})

@socketio.on("start_bot_game")
def handle_start_bot_game(data):
    sid = request.sid
    player_name = data.get("player_name", "").strip()
    logger.debug(f"Jogador {sid} iniciando jogo contra bot, nome: {player_name}")

    if not player_name or len(player_name) > 20:
        logger.error(f"Nome inválido: {player_name}")
        emit("error", {"message": "Digite um nome válido (1 a 20 caracteres)."})
        return

    # Cria uma sala especial para o jogo contra bot
    room_id = f"bot_{sid}"
    game_states[room_id] = {
        "board": [["" for _ in range(3)] for _ in range(3)],
        "current_player": "X",
        "winner": None,
        "game_over": False,
        "scoreboard": {player_name: 0, "Bot": 0, "Draw": 0},
        "players": {
            sid: {"role": "X", "name": player_name},
            "bot": {"role": "O", "name": "Bot"}
        },
        "is_bot_game": True
    }
    join_room(room_id)
    logger.debug(f"Jogador {sid} ({player_name}) iniciou jogo contra bot na sala {room_id}")

    # Envia o estado inicial
    emit("assign_role", {
        "role": "X",
        "message": f"Você é o jogador {player_name} (X) contra o Bot (O).",
        "room_id": room_id,
        "player_x_name": player_name,
        "player_o_name": "Bot"
    }, to=sid)

    emit("game_start", {
        "message": "Jogo contra Bot começou!",
        "board": game_states[room_id]["board"],
        "current_player": "X",
        "winner": None,
        "game_over": False,
        "scoreboard": game_states[room_id]["scoreboard"],
        "num_players": 2,
        "player_x_name": player_name,
        "player_o_name": "Bot"
    }, to=sid)

    emit("update", {
        "board": game_states[room_id]["board"],
        "current_player": "X",
        "winner": None,
        "game_over": False,
        "scoreboard": game_states[room_id]["scoreboard"],
        "num_players": 2,
        "player_x_name": player_name,
        "player_o_name": "Bot"
    }, to=sid)

@socketio.on("join_game")
def handle_join_game(data):
    sid = request.sid
    room_id = data.get("room_id")
    create_new = data.get("create_new", False)
    player_name = data.get("player_name", "").strip()
    logger.debug(f"Jogador {sid} tentando entrar na sala: {room_id}, create_new: {create_new}, nome: {player_name}")

    if not player_name or len(player_name) > 20:
        logger.error(f"Nome inválido: {player_name}")
        emit("error", {"message": "Digite um nome válido (1 a 20 caracteres)."})
        return

    if room_id and room_id not in game_states:
        logger.error(f"Sala inválida: {room_id}")
        emit("error", {"message": "Sala inválida ou não existe."})
        return
    if room_id and len(game_states[room_id]["players"]) >= 2:
        logger.warning(f"Sala {room_id} já tem 2 jogadores")
        emit("error", {"message": "Esta sala já tem 2 jogadores. Escolha outra sala."})
        return

    room_id = get_or_create_room(room_id, force_new=create_new)
    state = game_states[room_id]
    if len(state["players"]) >= 2:
        logger.warning(f"Sala {room_id} já tem 2 jogadores")
        emit("error", {"message": "Esta sala já tem 2 jogadores. Escolha outra sala."})
        disconnect()
        return

    if len(state["players"]) == 0:
        state["players"][sid] = {"role": "X", "name": player_name}
        role = "X"
        message = f"Você é o jogador {player_name} (X) na sala {room_id}. Aguardando o jogador O..."
        state["scoreboard"][player_name] = 0
    else:
        state["players"][sid] = {"role": "O", "name": player_name}
        role = "O"
        message = f"Você é o jogador {player_name} (O) na sala {room_id}. O jogo pode começar!"
        state["scoreboard"][player_name] = 0

    join_room(room_id)
    logger.debug(f"Jogador {sid} ({player_name}) entrou na sala {room_id} como {role}")

    player_x_name, player_o_name = get_player_names(room_id)
    emit("assign_role", {
        "role": role,
        "message": message,
        "room_id": room_id,
        "player_x_name": player_x_name,
        "player_o_name": player_o_name
    }, to=sid)

    if len(state["players"]) == 2:
        logger.debug(f"Sala {room_id}: Segundo jogador entrou, jogo começando")
        emit("game_start", {
            "message": f"Sala {room_id}: O jogo começou!",
            "board": state["board"],
            "current_player": state["current_player"],
            "winner": state["winner"],
            "game_over": state["game_over"],
            "scoreboard": state["scoreboard"],
            "num_players": len(state["players"]),
            "player_x_name": player_x_name,
            "player_o_name": player_o_name
        }, room=room_id)

    emit("update", {
        "board": state["board"],
        "current_player": state["current_player"],
        "winner": state["winner"],
        "game_over": state["game_over"],
        "scoreboard": state["scoreboard"],
        "num_players": len(state["players"]),
        "player_x_name": player_x_name,
        "player_o_name": player_o_name
    }, to=sid)

    emit("update_rooms", {"rooms": get_available_rooms()}, broadcast=True)

@socketio.on("leave_game")
def handle_leave_game(data):
    sid = request.sid
    room_id = data.get("room_id")
    logger.debug(f"Jogador {sid} tentando sair da sala: {room_id}")

    if not room_id or room_id not in game_states:
        logger.error(f"Sala inválida: {room_id}")
        emit("error", {"message": "Sala inválida."})
        return

    state = game_states[room_id]
    if sid not in state["players"]:
        logger.warning(f"Jogador {sid} não está na sala {room_id}")
        emit("error", {"message": "Você não está nesta sala."})
        return

    player_name = state["players"][sid]["name"]
    leave_room(room_id)
    del state["players"][sid]
    if player_name in state["scoreboard"]:
        del state["scoreboard"][player_name]

    logger.debug(f"Jogador {sid} ({player_name}) saiu da sala {room_id}")

    if state["is_bot_game"]:
        logger.debug(f"Removendo sala de bot: {room_id}")
        del game_states[room_id]
        emit("leave_game_success", {"message": "Você voltou ao menu."}, to=sid)
    else:
        player_x_name, player_o_name = get_player_names(room_id)
        if state["players"]:
            emit("player_left", {
                "message": f"{player_name} abandonou a partida. Você será redirecionado ao menu.",
                "player_x_name": player_x_name,
                "player_o_name": player_o_name,
                "force_menu": true
            }, room=room_id)
            state.update({
                "board": [["" for _ in range(3)] for _ in range(3)],
                "current_player": "X",
                "winner": None,
                "game_over": False
            })
            emit("update", {
                "board": state["board"],
                "current_player": state["current_player"],
                "winner": state["winner"],
                "game_over": state["game_over"],
                "scoreboard": state["scoreboard"],
                "num_players": len(state["players"]),
                "player_x_name": player_x_name,
                "player_o_name": player_o_name
            }, room=room_id)
        else:
            logger.debug(f"Sala {room_id} vazia, removendo")
            del game_states[room_id]

        emit("leave_game_success", {"message": "Você voltou ao menu."}, to=sid)

    emit("update_rooms", {"rooms": get_available_rooms()}, broadcast=True)

@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    logger.debug(f"Jogador {sid} desconectado")
    for room_id, state in list(game_states.items()):
        if sid in state["players"]:
            player_name = state["players"][sid]["name"]
            logger.debug(f"Jogador {sid} ({player_name}) saiu da sala {room_id} por desconexão")
            leave_room(room_id)
            del state["players"][sid]
            if player_name in state["scoreboard"]:
                del state["scoreboard"][player_name]
            if state["is_bot_game"]:
                logger.debug(f"Removendo sala de bot: {room_id}")
                del game_states[room_id]
            else:
                player_x_name, player_o_name = get_player_names(room_id)
                if state["players"]:
                    emit("player_left", {
                        "message": f"{player_name} abandonou a partida. Você será redirecionado ao menu.",
                        "player_x_name": player_x_name,
                        "player_o_name": player_o_name,
                        "force_menu": true
                    }, room=room_id)
                    state.update({
                        "board": [["" for _ in range(3)] for _ in range(3)],
                        "current_player": "X",
                        "winner": None,
                        "game_over": False
                    })
                    emit("update", {
                        "board": state["board"],
                        "current_player": state["current_player"],
                        "winner": state["winner"],
                        "game_over": state["game_over"],
                        "scoreboard": state["scoreboard"],
                        "num_players": len(state["players"]),
                        "player_x_name": player_x_name,
                        "player_o_name": player_o_name
                    }, room=room_id)
                else:
                    logger.debug(f"Sala {room_id} vazia, removendo")
                    del game_states[room_id]
            break
    emit("update_rooms", {"rooms": get_available_rooms()}, broadcast=True)

@socketio.on("make_move")
def handle_move(data):
    sid = request.sid
    room_id = data.get("room_id")
    if room_id not in game_states:
        logger.error(f"Sala inválida: {room_id}")
        emit("error", {"message": "Sala inválida."})
        return
    state = game_states[room_id]
    if sid not in state["players"]:
        logger.warning(f"Jogador {sid} não registrado na sala {room_id}")
        emit("error", {"message": "Você não está registrado como jogador."})
        return
    if not state["is_bot_game"] and len(state["players"]) < 2:
        logger.warning(f"Sala {room_id} tem apenas {len(state['players'])} jogador(es)")
        emit("error", {"message": "Aguardando o segundo jogador."})
        return
    if state["game_over"]:
        logger.warning(f"Sala {room_id}: Jogo encerrado")
        emit("error", {"message": "Jogo encerrado! Reinicie para jogar novamente."})
        return
    if state["players"][sid]["role"] != state["current_player"]:
        logger.warning(f"Jogador {sid} tentou jogar fora da vez na sala {room_id}")
        return

    row = data["row"]
    col = data["col"]

    if state["board"][row][col] == "":
        state["board"][row][col] = state["current_player"]
        winner = check_winner(state["board"])

        if winner:
            state["game_over"] = True
            state["winner"] = winner
            if winner != "Draw":
                for sid, info in state["players"].items():
                    if info["role"] == winner:
                        state["scoreboard"][info["name"]] += 1
                        break
            else:
                state["scoreboard"]["Draw"] += 1
        else:
            state["current_player"] = "O" if state["current_player"] == "X" else "X"

        logger.debug(f"Sala {room_id}: Jogada em ({row}, {col}) por {state['current_player']}")
        player_x_name, player_o_name = get_player_names(room_id)
        emit("update", {
            "board": state["board"],
            "current_player": state["current_player"],
            "winner": state["winner"],
            "game_over": state["game_over"],
            "scoreboard": state["scoreboard"],
            "num_players": len(state["players"]),
            "player_x_name": player_x_name,
            "player_o_name": player_o_name
        }, room=room_id)

        # Se for um jogo contra bot e não houver vencedor, o bot joga
        if state["is_bot_game"] and not state["game_over"] and state["current_player"] == "O":
            bot_move = bot_make_move(room_id)
            if bot_move:
                row, col = bot_move
                winner = check_winner(state["board"])
                if winner:
                    state["game_over"] = True
                    state["winner"] = winner
                    if winner != "Draw":
                        state["scoreboard"]["Bot"] += 1
                    else:
                        state["scoreboard"]["Draw"] += 1
                else:
                    state["current_player"] = "X"
                logger.debug(f"Sala {room_id}: Bot jogou em ({row}, {col})")
                emit("update", {
                    "board": state["board"],
                    "current_player": state["current_player"],
                    "winner": state["winner"],
                    "game_over": state["game_over"],
                    "scoreboard": state["scoreboard"],
                    "num_players": len(state["players"]),
                    "player_x_name": player_x_name,
                    "player_o_name": "Bot"
                }, room=room_id)
    else:
        return

@socketio.on("reset_game")
def reset_game(data):
    room_id = data.get("room_id")
    if room_id not in game_states:
        logger.error(f"Sala inválida: {room_id}")
        emit("error", {"message": "Sala inválida."})
        return
    state = game_states[room_id]
    if not state["is_bot_game"] and len(state["players"]) < 2:
        logger.warning(f"Sala {room_id}: Apenas {len(state['players'])} jogador(es) para reiniciar")
        emit("error", {"message": "Aguardando o segundo jogador."})
        return
    state.update({
        "board": [["" for _ in range(3)] for _ in range(3)],
        "current_player": "X",
        "winner": None,
        "game_over": False
    })
    logger.debug(f"Sala {room_id}: Jogo reiniciado")
    player_x_name, player_o_name = get_player_names(room_id)
    emit("update", {
        "board": state["board"],
        "current_player": state["current_player"],
        "winner": None,
        "game_over": False,
        "scoreboard": state["scoreboard"],
        "num_players": len(state["players"]),
        "player_x_name": player_x_name,
        "player_o_name": player_o_name
    }, room=room_id)

@socketio.on("reset_scoreboard")
def reset_scoreboard(data):
    room_id = data.get("room_id")
    if room_id not in game_states:
        logger.error(f"Sala inválida: {room_id}")
        emit("error", {"message": "Sala inválida."})
        return
    state = game_states[room_id]
    if not state["is_bot_game"] and len(state["players"]) < 2:
        logger.warning(f"Sala {room_id}: Apenas {len(state['players'])} jogador(es) para zerar placar")
        emit("error", {"message": "Aguardando o segundo jogador."})
        return
    new_scoreboard = {"Draw": 0}
    for sid, info in state["players"].items():
        new_scoreboard[info["name"]] = 0
    state.update({
        "board": [["" for _ in range(3)] for _ in range(3)],
        "current_player": "X",
        "winner": None,
        "game_over": False,
        "scoreboard": new_scoreboard
    })
    logger.debug(f"Sala {room_id}: Placar zerado")
    player_x_name, player_o_name = get_player_names(room_id)
    emit("update", {
        "board": state["board"],
        "current_player": state["current_player"],
        "winner": None,
        "game_over": False,
        "scoreboard": state["scoreboard"],
        "num_players": len(state["players"]),
        "player_x_name": player_x_name,
        "player_o_name": player_o_name
    }, room=room_id)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)