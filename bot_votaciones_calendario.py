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

# Configurar logging
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
# RUTA CORRECTA PARA tuna.txt
INPUT_FILE = r'C:\Users\karlo\Documents\tuna3.txt' 
OUTPUT_CALENDAR_HTML = os.path.join(BASE_DIR, 'calendar.html') # HTML del calendario
VOTES_FILE = os.path.join(BASE_DIR, 'votes.json') # Archivo para guardar los datos de votación
TEMPLATE_CALENDAR_HTML = os.path.join(BASE_DIR, 'template_calendario.html') # Plantilla para el calendario

TMDB_BASE = "https://api.themoviedb.org/3"

# Cambiamos el directorio actual al del repositorio git (BASE_DIR)
os.chdir(BASE_DIR)
logging.info(f"Cambiando directorio actual a: {BASE_DIR}")

# Configuración de Jinja2 para cargar plantillas desde BASE_DIR
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
        # Captura tanto stdout como stderr para evitar NoneType
        process = subprocess.run(["git", command, "."] if command == "add" else ["git", command, "-m", message], 
                                 check=True, capture_output=True)
        logging.info(f"Git: Comando '{command}' ejecutado. Salida: {process.stdout.decode('utf-8').strip()}")
    except subprocess.CalledProcessError as e:
        # Asegurarse de que e.stderr no sea None antes de decodificar
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
                # Asegurarse de que las claves existan si el archivo es antiguo
                data.setdefault("current_calendar_month", datetime.now().strftime("%Y-%m"))
                data.setdefault("current_movie_info", {})
                data.setdefault("votes_for_current_movie", {"total_score": 0, "num_votes": 0, "voters": []})
                data.setdefault("calendar", {})
                return data
        except json.JSONDecodeError as e:
            logging.error(f"Error al leer votes.json: {e}. Se inicializará un nuevo archivo.")
            return initialize_new_votes_data()
    return initialize_new_votes_data()

def initialize_new_votes_data():
    logging.info("Inicializando nuevo archivo votes.json.")
    return {
        "current_calendar_month": datetime.now().strftime("%Y-%m"),
        "current_movie_info": {}, # Información de la película actual (título, año, TMDB ID, póster)
        "votes_for_current_movie": {"total_score": 0, "num_votes": 0, "voters": []}, # Votos asociados a la película actual
        "calendar": {} # Historial de películas con sus notas finales
    }

def save_votes_data(data):
    try:
        with open(VOTES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        logging.error(f"Error al guardar votes.json: {e}")

def get_time_slot(hour):
    """Determina la ranura horaria basada en la hora."""
    if hour < 19: # Antes de las 7 PM (19:00)
        return "Sobremesa"
    else: # 7 PM (19:00) o después
        return "Noche de Cine"

def get_day_name(date_str):
    """Devuelve el nombre del día de la semana en español."""
    try:
        dt_object = datetime.strptime(date_str, "%Y-%m-%d")
        return dt_object.strftime("%A").capitalize()
    except ValueError:
        return "Día Desconocido"

def generate_full_month_days(year_month_str, calendar_data):
    """Genera una lista de días del mes, rellenando con datos existentes o None."""
    year, month = map(int, year_month_str.split('-'))
    # Calcular el número de días en el mes
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


# --- Función de generación del HTML del Calendario ---
def generar_html_calendario(calendar_data_raw, month_year_str):
    """Genera el HTML para el calendario (calendar.html)."""
    try:
        template = env.get_template(os.path.basename(TEMPLATE_CALENDAR_HTML))

        year = int(month_year_str.split('-')[0])
        month_num = int(month_year_str.split('-')[1])
        month_name = datetime(year, month_num, 1).strftime("%B").capitalize() # Nombre del mes en español

        # Prepara los datos del calendario incluyendo todos los días del mes
        calendar_for_template = generate_full_month_days(month_year_str, calendar_data_raw)
        
        rendered_html = template.render(
            year=year,
            month_name=month_name,
            calendar_for_template=calendar_for_template # Pasa la lista de días ordenada
        )
        with open(OUTPUT_CALENDAR_HTML, 'w', encoding='utf-8') as f:
            f.write(rendered_html)
    except Exception as e:
        logging.error(f"Error al generar {OUTPUT_CALENDAR_HTML}: {e}", exc_info=True)


# --- Bucle principal ---
def main():
    last_content_read = None # Último contenido de tuna.txt que fue procesado

    # Asegurarse de que el directorio BASE_DIR exista
    os.makedirs(BASE_DIR, exist_ok=True)
    logging.info(f"Directorio de trabajo: {BASE_DIR}")

    logging.info("Iniciando monitorización del archivo: " + INPUT_FILE)

    while True:
        try:
            # Asegurarse de que tuna.txt existe
            if not os.path.exists(INPUT_FILE):
                logging.warning(f"Archivo de entrada '{INPUT_FILE}' no encontrado. Creando uno vacío en {INPUT_FILE}.")
                # Asegúrate de tener permisos de escritura en C:\Users\karlo\Documents\
                with open(INPUT_FILE, 'w', encoding='utf-8') as f:
                    f.write('') # Crear un archivo vacío

            with open(INPUT_FILE, 'r', encoding='utf-8') as f:
                contenido_actual = f.read().strip()

            votes_data = load_votes_data() # Cargar los datos de votación

            # --- Manejo de cambio de mes ---
            current_month_str = datetime.now().strftime("%Y-%m")
            if votes_data["current_calendar_month"] != current_month_str:
                logging.info(f"Cambio de mes detectado. Reiniciando calendario de {votes_data['current_calendar_month']} a {current_month_str}.")
                votes_data["calendar"] = {}
                votes_data["current_calendar_month"] = current_month_str
                # Al cambiar de mes, la información de la película actual también se reinicia
                votes_data["current_movie_info"] = {}
                votes_data["votes_for_current_movie"] = {"total_score": 0, "num_votes": 0, "voters": []}
                
                save_votes_data(votes_data) # Guardar estado inicial del nuevo mes
                
                # Generar calendario vacío/limpio para el nuevo mes
                generar_html_calendario(votes_data["calendar"], votes_data["current_calendar_month"])
                
                run_git_command("add", "")
                run_git_command("commit", f"Reset calendario para {current_month_str}")
                run_git_command("push", "")


            # --- Procesamiento al detectar cambio en tuna.txt ---
            if contenido_actual != last_content_read:
                logging.info(f"Contenido de '{INPUT_FILE}' cambiado a: '{contenido_actual}'")

                # 1. Archivar la película ANTERIOR (si hubo y tenía votos)
                if votes_data["current_movie_info"] and votes_data["votes_for_current_movie"]["num_votes"] > 0:
                    prev_movie = votes_data["current_movie_info"]
                    prev_votes = votes_data["votes_for_current_movie"]
                    
                    try:
                        final_rating = round(prev_votes["total_score"] / prev_votes["num_votes"], 2)
                    except ZeroDivisionError:
                        final_rating = 0.0 # No hay votos, o num_votes es 0

                    # Usar la fecha de inicio de la película anterior para el calendario
                    # Si no hay 'start_time' o es inválido, usar la fecha actual como fallback
                    prev_start_dt = datetime.now() 
                    if "start_time" in prev_movie:
                        try:
                            prev_start_dt = datetime.fromisoformat(prev_movie["start_time"])
                        except ValueError:
                            logging.warning(f"start_time inválido en votes.json: {prev_movie['start_time']}. Usando fecha actual.")

                    prev_date_str = prev_start_dt.strftime("%Y-%m-%d")
                    prev_slot = prev_movie.get("time_slot", get_time_slot(prev_start_dt.hour)) # Usar la ranura que se le asignó al inicio, o inferirla

                    # Asegurarse de que el día exista en el calendario
                    if prev_date_str not in votes_data["calendar"]:
                        votes_data["calendar"][prev_date_str] = {"Sobremesa": None, "Noche de Cine": None}
                    
                    # Añadir la película al calendario
                    votes_data["calendar"][prev_date_str][prev_slot] = {
                        "title": prev_movie.get("title"),
                        "year": prev_movie.get("year"),
                        "poster_url": prev_movie.get("poster_url", ""),
                        "final_rating": final_rating,
                        "tmdb_id": prev_movie.get("tmdb_id")
                    }
                    logging.info(f"Película anterior '{prev_movie.get('title')}' archivada con nota media: {final_rating}.")

                # 2. Procesar el NUEVO contenido de tuna.txt para la 'current_movie_info' y reiniciar votos
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
                
                # Reiniciar votos para la (posiblemente nueva) película actual
                votes_data["votes_for_current_movie"] = {"total_score": 0, "num_votes": 0, "voters": []}
                
                # Guardar todos los cambios después de procesar
                save_votes_data(votes_data)
                
                # Generar el HTML del calendario después de cualquier cambio relevante
                generar_html_calendario(votes_data["calendar"], votes_data["current_calendar_month"])
                logging.info(f"HTML de calendario generado correctamente en: {OUTPUT_CALENDAR_HTML}")

                # Ejecutar comandos Git
                # run_git_command("add", "") # Estos comandos los ejecutarás manualmente una vez configurado Git
                # run_git_command("commit", f"Actualización automática de calendario ({contenido_actual})")
                # run_git_command("push", "")
                logging.info("Los comandos Git han sido deshabilitados en el script. Por favor, inicializa el repositorio Git manualmente y luego ejecuta los comandos `git add .`, `git commit` y `git push`.")
                
                last_content_read = contenido_actual # Actualizar el último contenido procesado
            
        except FileNotFoundError as e:
            logging.error(f"Error: Archivo no encontrado. Asegúrate de que '{INPUT_FILE}' y las plantillas existen. {e}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error de red o API TMDB: {e}")
        except Exception as e:
            logging.error(f"Error inesperado en el bucle principal: {e}", exc_info=True)

        time.sleep(10) # Esperar antes de la próxima comprobación

if __name__ == "__main__":
    main()