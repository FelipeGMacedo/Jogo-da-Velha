from flask import Flask, render_template
from flask_socketio import SocketIO, emit, disconnect, join_room, leave_room
from flask import request
import os
import uuid
import logging

app = Flask(__name__)
app.config["SECRET_KEY"] = "secret!"  # Necessário para Flask-SocketIO
socketio = SocketIO(app)

# Configura logging para depuração
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Dicionário para armazenar estados de todas as salas
game_states = {}

def get_or_create_room(room_id=None, force_new=False):
    """Retorna uma sala existente com menos de 2 jogadores ou cria uma nova."""
    logger.debug(f"Procurando sala para room_id: {room_id}, force_new: {force_new}")
    if not force_new:
        # Tenta usar o room_id fornecido, se válido
        if room_id and room_id in game_states and len(game_states[room_id]["players"]) < 2:
            logger.debug(f"Entrando na sala existente: {room_id}")
            return room_id
        # Procura uma sala com menos de 2 jogadores
        for rid, state in game_states.items():
            if len(state["players"]) < 2:
                logger.debug(f"Entrando na sala disponível: {rid}")
                return rid
    # Cria uma nova sala
    new_room_id = str(uuid.uuid4())[:8]  # ID único curto
    game_states[new_room_id] = {
        "board": [["" for _ in range(3)] for _ in range(3)],
        "current_player": "X",
        "winner": None,
        "game_over": False,
        "scoreboard": {"Draw": 0},  # Inicializa apenas Draw; nomes dos jogadores serão adicionados
        "players": {}  # Mapeia session_id para {role, name}
    }
    logger.debug(f"Criada nova sala: {new_room_id}")
    return new_room_id

def get_available_rooms():
    """Retorna a lista de salas com menos de 2 jogadores."""
    return [room_id for room_id, state in game_states.items() if len(state["players"]) < 2]

def check_winner(board):
    # Verifica linhas
    for row in board:
        if row[0] == row[1] == row[2] != "":
            return row[0]
    # Verifica colunas
    for col in range(3):
        if board[0][col] == board[1][col] == board[2][col] != "":
            return board[0][col]
    # Verifica diagonais
    if board[0][0] == board[1][1] == board[2][2] != "":
        return board[0][0]
    if board[0][2] == board[1][1] == board[2][0] != "":
        return board[0][2]
    # Verifica empate
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

@app.route("/")
def index():
    return render_template("index.html")

@socketio.on("connect")
def handle_connect():
    logger.debug(f"Novo cliente conectado: {request.sid}")
    # Envia a lista de salas disponíveis ao conectar
    emit("update_rooms", {"rooms": get_available_rooms()})

@socketio.on("get_rooms")
def handle_get_rooms():
    logger.debug(f"Cliente {request.sid} solicitou lista de salas")
    emit("update_rooms", {"rooms": get_available_rooms()})

@socketio.on("join_game")
def handle_join_game(data):
    sid = request.sid
    room_id = data.get("room_id")
    create_new = data.get("create_new", False)
    player_name = data.get("player_name", "").strip()
    logger.debug(f"Jogador {sid} tentando entrar na sala: {room_id}, create_new: {create_new}, nome: {player_name}")
    
    # Valida o nome do jogador
    if not player_name or len(player_name) > 20:
        logger.error(f"Nome inválido: {player_name}")
        emit("error", {"message": "Digite um nome válido (1 a 20 caracteres)."})
        return
    
    # Valida o room_id, se fornecido
    if room_id and room_id not in game_states:
        logger.error(f"Sala inválida: {room_id}")
        emit("error", {"message": "Sala inválida ou não existe."})
        return
    if room_id and len(game_states[room_id]["players"]) >= 2:
        logger.warning(f"Sala {room_id} já tem 2 jogadores")
        emit("error", {"message": "Esta sala já tem 2 jogadores. Escolha outra sala."})
        return

    # Obtém ou cria uma sala
    room_id = get_or_create_room(room_id, force_new=create_new)
    state = game_states[room_id]
    if len(state["players"]) >= 2:
        logger.warning(f"Sala {room_id} já tem 2 jogadores")
        emit("error", {"message": "Esta sala já tem 2 jogadores. Escolha outra sala."})
        disconnect()
        return

    # Atribui papel e nome ao jogador
    if len(state["players"]) == 0:
        state["players"][sid] = {"role": "X", "name": player_name}
        role = "X"
        message = f"Você é o jogador {player_name} (X) na sala {room_id}. Aguardando o jogador O..."
        state["scoreboard"][player_name] = 0  # Inicializa placar para o jogador
    else:
        state["players"][sid] = {"role": "O", "name": player_name}
        role = "O"
        message = f"Você é o jogador {player_name} (O) na sala {room_id}. O jogo pode começar!"
        state["scoreboard"][player_name] = 0  # Inicializa placar para o jogador

    # Adiciona o jogador à sala
    join_room(room_id)
    logger.debug(f"Jogador {sid} ({player_name}) entrou na sala {room_id} como {role}")
    
    # Envia o papel e o estado inicial do jogo
    player_x_name, player_o_name = get_player_names(room_id)
    emit("assign_role", {
        "role": role,
        "message": message,
        "room_id": room_id,
        "player_x_name": player_x_name,
        "player_o_name": player_o_name
    }, to=sid)
    
    # Notifica todos na sala se o jogo pode começar
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
    
    # Envia o estado do jogo
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

    # Atualiza a lista de salas para todos os clientes
    emit("update_rooms", {"rooms": get_available_rooms()}, broadcast=True)

@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    logger.debug(f"Jogador {sid} desconectado")
    # Procura a sala do jogador
    for room_id, state in list(game_states.items()):
        if sid in state["players"]:
            player_name = state["players"][sid]["name"]
            logger.debug(f"Jogador {sid} ({player_name}) saiu da sala {room_id}")
            leave_room(room_id)
            del state["players"][sid]
            # Remove o nome do placar
            if player_name in state["scoreboard"]:
                del state["scoreboard"][player_name]
            # Notifica os outros na sala
            player_x_name, player_o_name = get_player_names(room_id)
            emit("player_left", {
                "message": f"Sala {room_id}: {player_name} saiu. Aguardando novo jogador...",
                "player_x_name": player_x_name,
                "player_o_name": player_o_name
            }, room=room_id)
            # Reseta o jogo na sala
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
            # Remove a sala se estiver vazia
            if not state["players"]:
                logger.debug(f"Sala {room_id} vazia, removendo")
                del game_states[room_id]
            break
    # Atualiza a lista de salas para todos os clientes
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
    if len(state["players"]) < 2:
        logger.warning(f"Sala {room_id} tem apenas {len(state['players'])} jogador(es)")
        emit("error", {"message": "Aguardando o segundo jogador."})
        return
    if state["game_over"]:
        logger.warning(f"Sala {room_id}: Jogo encerrado")
        emit("error", {"message": "Jogo encerrado! Reinicie para jogar novamente."})
        return
    if state["players"][sid]["role"] != state["current_player"]:
        logger.warning(f"Jogador {sid} tentou jogar fora da vez na sala {room_id}")
        emit("error", {"message": "Não é a sua vez!"})
        return

    row = data["row"]
    col = data["col"]
    
    # Verifica se a jogada é válida
    if state["board"][row][col] == "":
        state["board"][row][col] = state["current_player"]
        winner = check_winner(state["board"])
        
        if winner:
            state["game_over"] = True
            state["winner"] = winner
            if winner != "Draw":
                # Incrementa o placar do jogador correspondente
                for sid, info in state["players"].items():
                    if info["role"] == winner:
                        state["scoreboard"][info["name"]] += 1
                        break
            else:
                state["scoreboard"]["Draw"] += 1
        else:
            state["current_player"] = "O" if state["current_player"] == "X" else "X"
        
        logger.debug(f"Sala {room_id}: Jogada em ({row}, {col}) por {state['current_player']}")
        # Envia o estado atualizado para todos na sala
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
    else:
        logger.warning(f"Sala {room_id}: Posição ({row}, {col}) já ocupada")
        emit("error", {"message": "Posição já ocupada!"}, to=sid)

@socketio.on("reset_game")
def reset_game(data):
    room_id = data.get("room_id")
    if room_id not in game_states:
        logger.error(f"Sala inválida: {room_id}")
        emit("error", {"message": "Sala inválida."})
        return
    state = game_states[room_id]
    if len(state["players"]) < 2:
        logger.warning(f"Sala {room_id}: Apenas {len(state['players'])} jogador(es) para reiniciar")
        emit("error", {"message": "Aguardando o segundo jogador."})
        return
    # Mantém o placar e jogadores, mas reinicia o tabuleiro e o estado do jogo
    state.update({
        "board": [["" for _ in range(3)] for _ in range(3)],
        "current_player": "X",
        "winner": None,
        "game_over": False
    })
    logger.debug(f"Sala {room_id}: Jogo reiniciado")
    # Envia o estado resetado para todos na sala
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
    if len(state["players"]) < 2:
        logger.warning(f"Sala {room_id}: Apenas {len(state['players'])} jogador(es) para zerar placar")
        emit("error", {"message": "Aguardando o segundo jogador."})
        return
    # Zera o placar e reinicia o jogo
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
    # Envia o estado atualizado para todos na sala
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