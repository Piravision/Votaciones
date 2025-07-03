import time
import os
import re
import configparser
import requests
from jinja2 import Environment, FileSystemLoader
import logging
import subprocess
from datetime import datetime, timedelta
import json
import locale
import sys # Asegurarse de que sys esté importado

# Configurar logging para la consola (solo afectará al script monitor si corre directamente)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# Configurar locale para nombres de meses y días en español (Windows/Linux)
try:
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_TIME, 'es_ES')
    except locale.Error:
        logging.warning("No se pudo configurar locale a 'es_ES.UTF-8' o 'es_ES'. Los nombres de días/meses podrían no estar en español.")

# Leer config.ini (asegúrate de que config.ini esté en la misma carpeta o ajusta la ruta)
config = configparser.ConfigParser()
config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
config.read(config_file_path)

API_KEY = config['TMDB']['api_key']

# Rutas para el nuevo proyecto de calendario
BASE_DIR = os.path.join('G:', os.sep, 'INFOPIRA', 'BOT', 'VOTACIONES')
INPUT_FILE = os.path.join(BASE_DIR, 'tuna.txt')
OUTPUT_CALENDAR_HTML = os.path.join(BASE_DIR, 'index.html') # CAMBIO AQUÍ: calendar.html a index.html
VOTES_FILE = os.path.join(BASE_DIR, 'votes.json')
TEMPLATE_CALENDAR_HTML = os.path.join(BASE_DIR, 'template_calendario.html')
VOTE_OUTPUT_FILE = os.path.join(BASE_DIR, 'voteoutput.txt')
DEBUG_VOTE_FILE = os.path.join(BASE_DIR, 'debug_vote.log') # Nuevo archivo de depuración

TMDB_BASE = "https://api.themoviedb.org/3" # ¡Asegúrate de que esta línea esté presente y correcta!

os.chdir(BASE_DIR)
logging.info(f"Cambiando directorio actual a: {BASE_DIR}")

env = Environment(loader=FileSystemLoader(BASE_DIR))

# --- Funciones de utilidad ---
def es_anuncio(texto):
    texto = texto.strip().lower()
    return texto.startswith("anuncio") or texto.startswith("anunciop")

def es_pelicula(texto):
    return bool(re.search(r"\(\d{4}\)$", texto.strip()))

def es_episodio(texto):
    return bool(re.search(r"S\d{2}E\d{2}", texto, re.IGNORECASE))

def extraer_datos_pelicula(texto):
    match = re.search(r"^(.*?)\s*\((\d{4})\)$", texto.strip())
    if match:
        return match.group(1).strip(), match.group(2)
    return None, None

def extraer_datos_episodio(texto):
    match = re.search(r"^(.*?)\s*S(\d{2})E(\d{2})$", texto.strip(), re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2), match.group(3)
    return None, None, None

def buscar_pelicula_serie(titulo, tipo, anio=None):
    params = {'api_key': API_KEY, 'query': titulo, 'language': 'es-ES'}
    url = f"{TMDB_BASE}/search/{tipo}"
    if anio:
        params['year'] = anio if tipo == 'movie' else None
        if tipo == 'tv':
            params['first_air_date_year'] = anio

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        results = response.json().get('results')
        if results:
            if tipo == 'tv' and anio:
                filtered_results = [r for r in results if str(datetime.strptime(r.get('first_air_date', '1900-01-01'), '%Y-%m-%d').year) == anio]
                if filtered_results:
                    return filtered_results[0]
            return results[0]
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al buscar en TMDB ({tipo}): {e}")
    return None

def obtener_detalles_serie(serie_id):
    url = f"{TMDB_BASE}/tv/{serie_id}"
    params = {'api_key': API_KEY, 'language': 'es-ES'}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al obtener detalles de la serie {serie_id}: {e}")
    return None

def procesar_contenido_tmdb(contenido):
    """Procesa el contenido de tuna.txt para obtener datos de TMDB para la película/serie actual."""
    if not es_anuncio(contenido) and contenido:
        if es_pelicula(contenido):
            title, year = extraer_datos_pelicula(contenido)
            if not title:
                logging.warning(f"No se pudo extraer título y año de la película: {contenido}")
                return None
            pelicula_data = buscar_pelicula_serie(title, 'movie', year)
            if pelicula_data:
                poster_path = pelicula_data.get('poster_path')
                poster_url = f"https://image.tmdb.org/t/p/w185{poster_path}" if poster_path else ''
                return {
                    "title": pelicula_data.get("title"),
                    "year": str(datetime.strptime(pelicula_data['release_date'], '%Y-%m-%d').year) if 'release_date' in pelicula_data else year,
                    "tmdb_id": pelicula_data['id'],
                    "poster_url": poster_url
                }
        elif es_episodio(contenido):
            series_title, season_num, episode_num = extraer_datos_episodio(contenido)
            if not all([series_title, season_num, episode_num]):
                logging.warning(f"No se pudo extraer título de serie, temporada y episodio: {contenido}")
                return None
            serie_data = buscar_pelicula_serie(series_title, 'tv')
            if serie_data:
                series_id = serie_data['id']
                details = obtener_detalles_serie(series_id)
                if details:
                    series_poster_path = details.get('poster_path')
                    series_poster = f"https://image.tmdb.org/t/p/w185{series_poster_path}" if series_poster_path else ''
                    return {
                        "title": details.get("name"), # Título de la serie
                        "year": str(datetime.strptime(details['first_air_date'], '%Y-%m-%d').year) if 'first_air_date' in details else 'N/A',
                        "tmdb_id": series_id,
                        "poster_url": series_poster
                    }
    return None


def run_git_command(command, message=""):
    try:
        if command == "add":
            process = subprocess.run(["git", command, "."], check=True, capture_output=True)
        elif command == "commit":
            # Verificar si hay cambios para commitear
            result = subprocess.run(["git", "diff", "--cached", "--exit-code"], capture_output=True)
            if result.returncode == 0: # No hay cambios para commitear
                logging.info("Git: No hay cambios para commitear.")
                return
            process = subprocess.run(["git", command, "-m", message], check=True, capture_output=True)
        elif command == "push":
            process = subprocess.run(["git", command, "origin", "main"], check=True, capture_output=True) # Asumimos 'main' como rama principal
        else:
            logging.warning(f"Comando Git '{command}' no reconocido.")
            return

        logging.info(f"Git: Comando '{command}' ejecutado. Salida: {process.stdout.decode('utf-8').strip()}")
    except subprocess.CalledProcessError as e:
        error_output = e.stderr.decode('utf-8').strip() if e.stderr else "Sin salida de error de Git."
        logging.error(f"Error ejecutando comando Git '{command}': {e.returncode}. Salida: {error_output}")
    except FileNotFoundError:
        logging.error("Git no está instalado o no está en el PATH.")


# --- Funciones para manejo de votos y calendario ---
def load_votes_data():
    if os.path.exists(VOTES_FILE):
        try:
            with open(VOTES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                data.setdefault("current_calendar_month", datetime.now().strftime("%Y-%m"))
                data.setdefault("current_movie_info", {})
                data.setdefault("votes_for_current_movie", {"total_score": 0, "num_votes": 0, "voters": [], "detailed_votes": []})
                if "voters" in data["votes_for_current_movie"] and "detailed_votes" not in data["votes_for_current_movie"]:
                    data["votes_for_current_movie"]["detailed_votes"] = []
                data.setdefault("calendar", {})
                data.setdefault("global_user_votes", {})
                return data
        except json.JSONDecodeError as e:
            logging.error(f"Error al leer votes.json: {e}. Se inicializará un nuevo archivo.")
            return initialize_new_votes_data()
    return initialize_new_votes_data()

def initialize_new_votes_data():
    logging.info("Inicializando nuevo archivo votes.json.")
    return {
        "current_calendar_month": datetime.now().strftime("%Y-%m"),
        "current_movie_info": {},
        "votes_for_current_movie": {"total_score": 0, "num_votes": 0, "voters": [], "detailed_votes": []},
        "calendar": {},
        "global_user_votes": {}
    }

def save_votes_data(data):
    try:
        with open(VOTES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        logging.error(f"Error al guardar votes.json: {e}")

def write_bot_response_to_file(message):
    try:
        with open(VOTE_OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write(message + "\n")
        logging.info(f"Mensaje de respuesta escrito en: {VOTE_OUTPUT_FILE}")
    except IOError as e:
        logging.error(f"Error al escribir el mensaje de respuesta en '{VOTE_OUTPUT_FILE}': {e}")

# Nuevo: Función para escribir logs de depuración del voto
def write_debug_log_to_file(message):
    try:
        with open(DEBUG_VOTE_FILE, 'a', encoding='utf-8') as f: # Usar 'a' para modo append
            f.write(f"{datetime.now().isoformat()} [DEBUG] {message}\n")
    except IOError as e:
        # Usar logging normal para errores de escritura de depuración, ya que este es el último recurso
        logging.error(f"Error al escribir el mensaje de depuración en '{DEBUG_VOTE_FILE}': {e}")


def register_user_vote(username, raw_input_score_string):
    """
    Registra el voto de un usuario para la película actual y actualiza el calendario.
    username: El nombre de usuario que emite el voto.
    raw_input_score_string: La cadena completa del %rawInput% (ej. "7" o "8.5").
    """
    write_debug_log_to_file(f"Intento de registro de voto de '{username}' con raw_input_score_string: '{raw_input_score_string}'.")
    write_debug_log_to_file(f"Raw score argument received: '{raw_input_score_string}' (type: {type(raw_input_score_string)})")

    # Extraer solo el número del inicio de raw_input_score_string
    # Esto es por si %rawInput% incluye el comando como "!voto 7"
    # Aunque Streamer Bot suele quitar el comando si se usa %rawInput% después del comando.
    # Esta regex busca un número al inicio de la cadena, opcionalmente con decimales.
    score_match = re.match(r'^\s*(\d+(\.\d+)?)\s*$', raw_input_score_string.strip())

    if not score_match:
        message = f"@{username}, por favor, introduce una nota válida (un número) después de !voto (ej. !voto 8.5)."
        write_debug_log_to_file(f"No se encontró un número válido en raw_input_score_string: '{raw_input_score_string}'.")
        write_bot_response_to_file(message)
        return

    stripped_score = score_match.group(1) # Obtener el número capturado por la regex
    write_debug_log_to_file(f"Extraído score de raw_input_score_string: '{stripped_score}' (type: {type(stripped_score)})")

    try:
        score_val = float(stripped_score)
        if not (0 <= score_val <= 10):
            message = f"@{username}, la nota debe ser un número entre 0 y 10."
            write_debug_log_to_file(message)
            write_bot_response_to_file(message)
            return

        votes_data = load_votes_data()

        current_movie = votes_data.get("current_movie_info")
        write_debug_log_to_file(f"current_movie_info loaded: {current_movie}")
        if not current_movie or not current_movie.get("title"):
            # CAMBIO AQUÍ: Mensaje específico cuando no hay película para votar
            message = f"@{username}, las votaciones solo están abiertas en la Sobremesa y en las Noches de Cine. Lo sentimos, su voto no ha sido registrado. 🎬"
            write_debug_log_to_file(message)
            write_bot_response_to_file(message)
            return

        current_movie_title = current_movie["title"]
        current_votes = votes_data["votes_for_current_movie"]

        user_already_voted_this_session = False
        for vote_entry in current_votes["detailed_votes"]:
            if vote_entry.get("user", "").lower() == username.lower():
                user_already_voted_this_session = True
                break

        if user_already_voted_this_session:
            message = f"@{username}, ¡Ya has votado por '{current_movie_title}' en esta sesión! Tu voto ya está registrado. 👍"
            write_debug_log_to_file(message)
            write_bot_response_to_file(message)
            return

        current_votes["total_score"] += score_val
        current_votes["num_votes"] += 1

        current_votes["detailed_votes"].append({
            "user": username,
            "score": score_val,
            "timestamp": datetime.now().isoformat()
        })

        votes_data["global_user_votes"][username] = votes_data["global_user_votes"].get(username, 0) + 1

        save_votes_data(votes_data)

        sorted_top_voters = sorted(votes_data["global_user_votes"].items(), key=lambda item: item[1], reverse=True)[:10]
        generar_html_calendario(votes_data["calendar"], votes_data["current_calendar_month"], sorted_top_voters)

        # CAMBIO AQUÍ: Mensaje de éxito mejorado
        message = f"¡Felicidades @{username}! Has votado con un {score_val} a '{current_movie_title}'. Tu voto ha sido registrado. Puedes consultar la nota final de los Piraviewers y el historial de películas en: https://piravision.github.io/Votaciones/"
        write_debug_log_to_file(message)
        write_bot_response_to_file(message)

    except ValueError:
        message = f"@{username}, por favor, introduce una nota válida (número) después de !voto (ej. !voto 8.5)."
        write_debug_log_to_file(f"ValueError: No se pudo convertir '{stripped_score}' a float. Detalles de la excepción: {sys.exc_info()}")
        write_bot_response_to_file(message)
    except Exception as e:
        message = f"@{username}, ¡Lo siento! Hubo un error al registrar tu voto. Por favor, inténtalo de nuevo más tarde."
        write_debug_log_to_file(f"Error inesperado en register_user_vote: {e}. Detalles de la excepción: {sys.exc_info()}")
        write_bot_response_to_file(message)

def get_time_slot(hour):
    if 12 <= hour < 19:
        return "Sobremesa"
    elif (20 <= hour <= 23) or (0 <= hour <= 6):
        return "Noche de Cine"
    else:
        return "Noche de Cine" # Caso por defecto o cualquier otra hora

def get_day_name(date_str):
    try:
        dt_object = datetime.strptime(date_str, "%Y-%m-%d")
        return dt_object.strftime("%A").capitalize()
    except ValueError:
        return "Día Desconocido"

def generate_full_month_days(year_month_str, calendar_data):
    year, month = map(int, year_month_str.split('-'))
    last_day_of_month = (datetime(year, month % 12 + 1, 1) - timedelta(days=1)).day if month < 12 else (datetime(year + 1, 1, 1) - timedelta(days=1)).day

    full_calendar_view = []
    for day in range(1, last_day_of_month + 1):
        date_str = f"{year_month_str}-{day:02d}"
        dt_object = datetime.strptime(date_str, "%Y-%m-%d")

        day_entry = {
            'date': date_str,
            'day_name': dt_object.strftime("%A").capitalize(),
            'slots': calendar_data.get(date_str, {
                "Sobremesa": None,
                "Noche de Cine": None
            })
        }
        full_calendar_view.append(day_entry)
    return full_calendar_view

def generar_html_calendario(calendar_data, current_month_str, top_voters_data):
    template = env.get_template(os.path.basename(TEMPLATE_CALENDAR_HTML))

    full_calendar_view = generate_full_month_days(current_month_str, calendar_data)

    month_name = datetime.strptime(current_month_str, "%Y-%m").strftime("%B").capitalize()
    year = datetime.strptime(current_month_str, "%Y-%m").year

    rendered_html = template.render(
        calendar_for_template=full_calendar_view,
        month_name=month_name,
        year=year,
        top_voters=top_voters_data
    )

    with open(OUTPUT_CALENDAR_HTML, 'w', encoding='utf-8') as f:
        f.write(rendered_html)
    logging.info(f"HTML de calendario generado correctamente en: {OUTPUT_CALENDAR_HTML}") # Movido aquí para ser más específico

# --- Bucle principal ---
def main():
    last_content_read = None

    os.makedirs(BASE_DIR, exist_ok=True)
    logging.info(f"Directorio de trabajo: {BASE_DIR}")

    logging.info("Iniciando monitorización del archivo: " + INPUT_FILE)

    while True:
        try:
            if not os.path.exists(INPUT_FILE):
                logging.warning(f"Archivo de entrada '{INPUT_FILE}' no encontrado. Creando uno vacío en {INPUT_FILE}.")
                with open(INPUT_FILE, 'w', encoding='utf-8') as f:
                    f.write('')

            with open(INPUT_FILE, 'r', encoding='utf-8') as f:
                contenido_actual = f.read().strip()

            votes_data = load_votes_data()

            current_month_str = datetime.now().strftime("%Y-%m")
            if votes_data["current_calendar_month"] != current_month_str:
                logging.info(f"Cambio de mes detectado. Reiniciando calendario de {votes_data['current_calendar_month']} a {current_month_str}.")
                votes_data["calendar"] = {}
                votes_data["current_calendar_month"] = current_month_str
                votes_data["current_movie_info"] = {}
                votes_data["votes_for_current_movie"] = {"total_score": 0, "num_votes": 0, "voters": [], "detailed_votes": []}

                save_votes_data(votes_data)

                sorted_top_voters = sorted(votes_data["global_user_votes"].items(), key=lambda item: item[1], reverse=True)[:10]
                generar_html_calendario(votes_data["calendar"], votes_data["current_calendar_month"], sorted_top_voters)

                # Comandos Git para el cambio de mes (estos ya estaban bien)
                run_git_command("add", "")
                run_git_command("commit", f"Reset calendario para {current_month_str}")
                run_git_command("push", "")


            if contenido_actual != last_content_read:
                logging.info(f"Contenido de '{INPUT_FILE}' cambiado a: '{contenido_actual}'")

                if votes_data["current_movie_info"] and votes_data["votes_for_current_movie"]["num_votes"] > 0:
                    prev_movie = votes_data["current_movie_info"]
                    prev_votes = votes_data["votes_for_current_movie"]

                    try:
                        final_rating = round(prev_votes["total_score"] / prev_votes["num_votes"], 2)
                    except ZeroDivisionError:
                        final_rating = 0.0

                    if "detailed_votes" in prev_votes and isinstance(prev_votes["detailed_votes"], list):
                        for vote_entry in prev_votes["detailed_votes"]:
                            user = vote_entry.get("user")
                            if user:
                                # Aquí es donde se actualiza global_user_votes al finalizar una película
                                votes_data["global_user_votes"][user] = votes_data["global_user_votes"].get(user, 0) + 1
                    else:
                        logging.warning("No se encontraron 'detailed_votes' para la película anterior. No se actualizarán los votos de los usuarios.")

                    prev_start_dt = datetime.now()
                    if "start_time" in prev_movie:
                        try:
                            prev_start_dt = datetime.fromisoformat(prev_movie["start_time"])
                        except ValueError:
                            logging.warning(f"start_time inválido en votes.json: {prev_movie['start_time']}. Usando fecha actual.")

                    prev_date_str = prev_start_dt.strftime("%Y-%m-%d")
                    prev_slot = prev_movie.get("time_slot", get_time_slot(prev_start_dt.hour))

                    if prev_date_str not in votes_data["calendar"]:
                        votes_data["calendar"][prev_date_str] = {"Sobremesa": None, "Noche de Cine": None}

                    votes_data["calendar"][prev_date_str][prev_slot] = {
                        "title": prev_movie.get("title"),
                        "year": prev_movie.get("year"),
                        "poster_url": prev_movie.get("poster_url", ""),
                        "final_rating": final_rating,
                        "tmdb_id": prev_movie.get("tmdb_id")
                    }
                    logging.info(f"Película anterior '{prev_movie.get('title')}' archivada con nota media: {final_rating}.")

                processed_movie_info = None
                if not es_anuncio(contenido_actual) and contenido_actual:
                    processed_movie_info = procesar_contenido_tmdb(contenido_actual)

                if processed_movie_info:
                    current_hour = datetime.now().hour
                    time_slot = get_time_slot(current_hour)
                    processed_movie_info["time_slot"] = time_slot
                    processed_movie_info["start_time"] = datetime.now().isoformat()

                    votes_data["current_movie_info"] = processed_movie_info
                    logging.info(f"Información de película actual actualizada para: {processed_movie_info.get('title')}")
                else:
                    logging.info("Se ha detectado 'Anuncio' o el contenido no es válido, se limpia la información de la película actual.")
                    votes_data["current_movie_info"] = {}

                votes_data["votes_for_current_movie"] = {"total_score": 0, "num_votes": 0, "voters": [], "detailed_votes": []}

                save_votes_data(votes_data)

                sorted_top_voters = sorted(votes_data["global_user_votes"].items(), key=lambda item: item[1], reverse=True)[:10]
                generar_html_calendario(votes_data["calendar"], votes_data["current_calendar_month"], sorted_top_voters)

                # CAMBIO AQUÍ: Activación de comandos Git al detectar cambio en tuna.txt
                run_git_command("add", "")
                run_git_command("commit", f"Actualización automática de calendario para '{contenido_actual}'")
                run_git_command("push", "")
                logging.info("Comandos Git ejecutados automáticamente.") # Mensaje de confirmación

                last_content_read = contenido_actual

        except FileNotFoundError as e:
            logging.error(f"Error: Archivo no encontrado. Asegúrate de que '{INPUT_FILE}' y las plantillas existen. {e}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error de red o API TMDB: {e}")
        except Exception as e:
            logging.error(f"Error inesperado en el bucle principal: {e}", exc_info=True)

        time.sleep(10)

if __name__ == "__main__":
    if len(sys.argv) == 1:
        main()
    elif len(sys.argv) == 4 and sys.argv[1] == "register_vote":
        username_arg = sys.argv[2]
        score_arg = sys.argv[3] # Mantener el original aquí para que la función register_user_vote haga la limpieza
        register_user_vote(username_arg, score_arg)
    else:
        print("Uso: python bot_votaciones_calendario.py (para ejecutar el monitor) o")
        print("         python bot_votaciones_calendario.py register_vote <username> <score> (para registrar un voto)")