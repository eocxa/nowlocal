"""
servidor_completo.py - Reproductor Local Completo de Audio (M4A/MP3/FLAC)
Soporta:
- Selección de directorio local con canciones y subcarpetas recursivas.
- Lectura de letras sincronizadas locales (.lrc y .ttml) y embebidas.
- Streaming de audio optimizado con soporte de HTTP Range (Seek instantáneo).
- Extracción automática de carátulas embebidas y metadatos (ID4 / Mutagen).
- Fallback inteligente a LRCLIB si la canción no tiene letra local.
"""

import asyncio
import atexit
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

try:
    import mutagen
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.id3 import ID3, APIC, USLT, SYLT
    from mutagen.flac import FLAC
except ImportError:
    print("[AVISO] mutagen no está instalado. Ejecuta: pip install mutagen")
    mutagen = None

try:
    from PIL import Image
except ImportError:
    Image = None

# ============================================================
# CONFIGURACIÓN
# ============================================================
PUERTO = int(os.environ.get("PORT", 8000))
CARPETA_COMPLETO = os.path.dirname(os.path.abspath(__file__))
RUTA_CONFIG = os.path.join(CARPETA_COMPLETO, "config.json")
RUTA_HTML = os.path.join(CARPETA_COMPLETO, "index.html")
RUTA_MOVIL = os.path.join(CARPETA_COMPLETO, "movil.html")
DIR_CACHE_COVERS = os.path.join(CARPETA_COMPLETO, ".cache_covers")
os.makedirs(DIR_CACHE_COVERS, exist_ok=True)
CACHE_COVERS_MEM: Dict[str, tuple] = {}
DIR_CACHE_AUDIO = os.path.join(CARPETA_COMPLETO, ".cache_audio")
os.makedirs(DIR_CACHE_AUDIO, exist_ok=True)
AUDIO_LOCKS: Dict[str, asyncio.Lock] = {}

# Configuración de Límites de Caché de Audio (2 GB máximo con política LRU)
MAX_CACHE_AUDIO_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
TARGET_CACHE_AUDIO_BYTES = int(1.6 * 1024 * 1024 * 1024)  # 1.6 GB objetivo al purgar

def obtener_tamano_cache_audio() -> int:
    """Calcula el tamaño total en bytes de los archivos en DIR_CACHE_AUDIO."""
    total = 0
    try:
        for entry in os.scandir(DIR_CACHE_AUDIO):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return total

def limpiar_archivos_temporales():
    """Elimina archivos .tmp residuales que hayan quedado huérfanos."""
    try:
        for entry in os.scandir(DIR_CACHE_AUDIO):
            if entry.is_file() and entry.name.endswith(".tmp"):
                try:
                    os.remove(entry.path)
                except Exception:
                    pass
    except Exception:
        pass

def limpiar_lru_cache_audio(espacio_requerido: int = 0):
    """
    Opción 2: Mantiene la caché estrictamente bajo el límite de 2 GB.
    Si el tamaño total excede 2 GB, purga los archivos menos recientemente usados (LRU)
    hasta alcanzar 1.6 GB.
    """
    total = obtener_tamano_cache_audio()
    if total + espacio_requerido <= MAX_CACHE_AUDIO_BYTES:
        return

    print(f"[CACHE LRU] Caché de audio ({total / (1024**3):.2f} GB) se acerca al límite de 2 GB. Purgando pistas antiguas...")
    archivos = []
    try:
        for entry in os.scandir(DIR_CACHE_AUDIO):
            if entry.is_file() and not entry.name.endswith(".tmp"):
                try:
                    st = entry.stat()
                    tiempo_uso = max(st.st_atime, st.st_mtime)
                    archivos.append((tiempo_uso, st.st_size, entry.path))
                except OSError:
                    pass
    except Exception as e:
        print(f"[CACHE LRU] Error escaneando carpeta de caché: {e}")
        return

    archivos.sort(key=lambda x: x[0])
    purgados = 0
    for _, size, path in archivos:
        if total <= TARGET_CACHE_AUDIO_BYTES:
            break
        try:
            os.remove(path)
            total -= size
            purgados += 1
        except Exception:
            pass

    print(f"[CACHE LRU] Purgado completado ({purgados} archivos eliminados). Tamaño actual: {total / (1024**3):.2f} GB.")

def limpiar_cache_audio_completa():
    """
    Opción 1: Borra la totalidad de archivos en .cache_audio al cerrar el servidor
    para liberar espacio en disco y no dejar gigabytes guardados al apagar la app.
    """
    print("\n[CACHE] Cerrando servidor: eliminando caché de audio temporal...")
    limpiados = 0
    try:
        for entry in os.scandir(DIR_CACHE_AUDIO):
            if entry.is_file():
                try:
                    os.remove(entry.path)
                    limpiados += 1
                except Exception:
                    pass
        print(f"[CACHE] Limpieza completada ({limpiados} archivos eliminados).")
    except Exception as e:
        print(f"[CACHE] Error limpiando caché: {e}")

atexit.register(limpiar_cache_audio_completa)

def redimensionar_imagen_bytes(data_bytes: bytes, target_size: int) -> Optional[bytes]:
    """Genera miniatura optimizada de forma ultra rápida preservando alta nitidez."""
    if not Image:
        return None
    try:
        import io
        with Image.open(io.BytesIO(data_bytes)) as img:
            if img.mode in ("RGBA", "LA", "P"):
                rgb = Image.new("RGB", img.size, (24, 24, 28))
                if img.mode == "RGBA":
                    rgb.paste(img, mask=img.split()[-1])
                else:
                    rgba = img.convert("RGBA")
                    rgb.paste(rgba, mask=rgba.split()[-1])
                img = rgb
            elif img.mode != "RGB":
                img = img.convert("RGB")
            
            img.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            return buf.getvalue()
    except Exception as e:
        print(f"[THUMB] Error redimensionando portada a {target_size}px: {e}")
        return None



def formatear_compositores(comp_val) -> str:
    """Normaliza y limpia la lista de compositores separados por comas."""
    if not comp_val:
        return ""
    if isinstance(comp_val, (list, tuple)):
        raw = ", ".join(str(x) for x in comp_val)
    else:
        raw = str(comp_val)
    # Separar por comas, punto y coma, barra o ampersand
    parts = [p.strip() for p in re.split(r'[,;/&]+', raw) if p.strip()]
    seen = set()
    dedup = [x for x in parts if not (x.lower() in seen or seen.add(x.lower()))]
    return ", ".join(dedup)

def es_movil(user_agent: str) -> bool:
    """Detecta teléfonos por User-Agent (iPhone/iPod siempre; Android solo si trae 'Mobile',
    para no capturar tablets Android que usan la interfaz de escritorio)."""
    ua = (user_agent or "").lower()
    if "iphone" in ua or "ipod" in ua:
        return True
    return "android" in ua and "mobile" in ua

EXTS_AUDIO = {".m4a", ".mp3", ".flac", ".wav", ".aac", ".ogg", ".opus", ".m4b"}

def normalizar_directorio(dir_str: str) -> str:
    if not dir_str:
        return ""
    d = str(dir_str).strip().strip('"').strip("'").strip()
    d = os.path.expanduser(d)
    d = os.path.expandvars(d)
    d = os.path.normpath(d)
    return d

# Estado en memoria
config_data = {
    "music_dir": os.path.join(os.path.expanduser("~"), "Music"),
    "queue_order": []
}
biblioteca_tracks: List[Dict[str, Any]] = []
biblioteca_folders: List[Dict[str, Any]] = []
tracks_by_id: Dict[str, Dict[str, Any]] = {}
CACHE_LETRAS: Dict[str, List[Dict[str, Any]]] = {}

# Cargar config guardada
if os.path.exists(RUTA_CONFIG):
    try:
        with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
            saved = json.load(f)
            if "music_dir" in saved and saved["music_dir"]:
                norm_dir = normalizar_directorio(saved["music_dir"])
                if norm_dir and os.path.exists(norm_dir):
                    config_data["music_dir"] = norm_dir
            if isinstance(saved.get("queue_order"), list):
                config_data["queue_order"] = saved["queue_order"]
    except Exception as e:
        print(f"[CONFIG] Error cargando config.json: {e}")

# Variable de entorno MUSIC_DIR tiene prioridad (ideal para Docker / VPS / Servidores)
env_music_dir = os.environ.get("MUSIC_DIR")
if env_music_dir:
    norm_env = normalizar_directorio(env_music_dir)
    if norm_env:
        config_data["music_dir"] = norm_env

app = FastAPI(title="Now Playing - Reproductor Completo", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def guardar_config():
    try:
        with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[CONFIG] Error guardando config.json: {e}")

# ============================================================
# PARSEADORES DE LETRAS (LRC & TTML)
# ============================================================
def parse_tiempo_str(t_str: str) -> float:
    """Convierte marcas de tiempo en segundos (ej: '01:23.45', '00:01:23.450', '83.4s')."""
    if not t_str:
        return 0.0
    t_str = t_str.strip().rstrip("s").rstrip("S").replace(",", ".")
    
    # Formato HH:MM:SS.mmm o MM:SS.mmm
    partes = t_str.split(":")
    try:
        if len(partes) == 3:
            h = float(partes[0])
            m = float(partes[1])
            s = float(partes[2])
            return h * 3600.0 + m * 60.0 + s
        elif len(partes) == 2:
            m = float(partes[0])
            s = float(partes[1])
            return m * 60.0 + s
        elif len(partes) == 1:
            return float(partes[0])
    except Exception:
        pass
    return 0.0

def parsear_lrc(contenido: str) -> List[Dict[str, Any]]:
    """Parsea texto LRC respetando líneas, intros y pausas instrumentales (> 4.5s)."""
    lineas_raw = []
    patron_ts = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")

    for linea in contenido.splitlines():
        linea_str = linea.strip()
        if not linea_str:
            continue
        coincidencias = patron_ts.findall(linea_str)
        if coincidencias:
            texto = patron_ts.sub("", linea_str).strip()
            if not texto or texto in {"…", "...", "&#x2026;"}:
                texto = "…"
            for m, s, ms in coincidencias:
                minutos = int(m)
                segundos = int(s)
                milis = int(ms.ljust(3, "0")[:3]) if ms else 0
                seg_total = minutos * 60 + segundos + milis / 1000.0
                lineas_raw.append((seg_total, None, texto))
        else:
            m_simple = re.match(r"^\[(\d+):(\d+(?:\.\d+)?)\](.*)$", linea_str)
            if m_simple:
                m_val = float(m_simple.group(1))
                s_val = float(m_simple.group(2))
                txt_val = m_simple.group(3).strip()
                if not txt_val or txt_val in {"…", "...", "&#x2026;"}:
                    txt_val = "…"
                lineas_raw.append((m_val * 60.0 + s_val, None, txt_val))

    lineas_raw.sort(key=lambda x: x[0])
    return procesar_lineas_finales(lineas_raw)

def enriquecer_adlibs(linea: Dict[str, Any]) -> Dict[str, Any]:
    """Detecta adlibs / coros / voces de fondo entre paréntesis (...) y los separa de la voz principal, eliminando los paréntesis."""
    txt = linea.get("text", "")
    words = linea.get("words", [])
    
    m = re.search(r'\(([^)]+)\)', txt)
    if m and txt not in {"…", "..."}:
        raw_adlib = m.group(0).strip()
        pure_adlib = m.group(1).strip()
        main_content = re.sub(r'\s*\([^)]+\)\s*', ' ', txt).strip()
        
        if main_content:
            raw_main_words = []
            raw_adlib_words = []
            inside = False
            for w in words:
                w_txt = w.get("text", "")
                if "(" in w_txt:
                    inside = True
                if inside:
                    raw_adlib_words.append(w)
                else:
                    raw_main_words.append(w)
                if ")" in w_txt:
                    inside = False
            
            # Limpiar paréntesis de cada palabra individual
            main_words = []
            for w in raw_main_words:
                c_txt = w["text"].replace("(", "").replace(")", "")
                if c_txt:
                    main_words.append({
                        "time": w["time"],
                        "endTime": w.get("endTime"),
                        "text": c_txt
                    })
                    
            adlib_words = []
            for w in raw_adlib_words:
                c_txt = w["text"].replace("(", "").replace(")", "")
                if c_txt:
                    adlib_words.append({
                        "time": w["time"],
                        "endTime": w.get("endTime"),
                        "text": c_txt
                    })

            for w_idx in range(len(main_words)):
                if main_words[w_idx].get("endTime") is None:
                    if w_idx + 1 < len(main_words):
                        main_words[w_idx]["endTime"] = main_words[w_idx + 1]["time"]
                    else:
                        main_words[w_idx]["endTime"] = linea.get("endTime")

            for w_idx in range(len(adlib_words)):
                if adlib_words[w_idx].get("endTime") is None:
                    if w_idx + 1 < len(adlib_words):
                        adlib_words[w_idx]["endTime"] = adlib_words[w_idx + 1]["time"]
                    else:
                        adlib_words[w_idx]["endTime"] = linea.get("endTime")
            
            m_time = main_words[0]["time"] if main_words else linea["time"]
            a_time = adlib_words[0]["time"] if adlib_words else linea["time"]
            adlib_is_before = (a_time < m_time) if (main_words and adlib_words) else (txt.find(raw_adlib) == 0)
            
            linea["has_adlib"] = True
            linea["adlib_is_before"] = adlib_is_before
            linea["main"] = {
                "text": main_content,
                "words": main_words,
                "time": m_time,
                "endTime": main_words[-1].get("endTime") if main_words else linea.get("endTime")
            }
            linea["adlib"] = {
                "text": pure_adlib,
                "words": adlib_words,
                "time": a_time,
                "endTime": adlib_words[-1].get("endTime") if adlib_words else linea.get("endTime")
            }
        else:
            linea["is_full_adlib"] = True
    else:
        linea["has_adlib"] = False
        
    return linea

def parsear_ttml(contenido: str) -> List[Dict[str, Any]]:
    """Parsea archivos TTML / XML respetando etiquetas <p>, spans palabra por palabra (karaoke), begin/end, adlibs y pausas."""
    lineas = []
    
    # 1. Encontrar todos los bloques <p ...>...</p>
    patron_p = re.findall(r'<p([^>]*)>(.*?)</p>', contenido, flags=re.DOTALL | re.IGNORECASE)
    
    for p_attrs, p_content in patron_p:
        m_begin = re.search(r'begin="([^"]+)"', p_attrs, flags=re.IGNORECASE)
        m_end = re.search(r'end="([^"]+)"', p_attrs, flags=re.IGNORECASE)
        
        if not m_begin:
            continue
            
        p_begin = parse_tiempo_str(m_begin.group(1))
        p_end = parse_tiempo_str(m_end.group(1)) if m_end else None
        
        # Eliminar etiquetas contenedoras intermedias como <span ttm:role="x-bg"> que no tienen begin=
        cleaned_p = re.sub(r'<span(?![^>]*begin=)[^>]*>', '', p_content)

        # Extraer spans hijos hoja que contienen begin="..." junto con sus espacios intermedios
        spans_raw = re.findall(r'<span([^>]*begin="[^"]+"[^>]*)>(.*?)</span>([^<]*)', cleaned_p, flags=re.DOTALL | re.IGNORECASE)
        words_list = []
        full_text_parts = []
        
        if spans_raw:
            for s_attrs, s_text, s_tail in spans_raw:
                s_comb = s_text + (s_tail if s_tail else "")
                s_clean = re.sub(r'<[^>]+>', '', s_comb)
                s_clean = s_clean.replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                
                m_s_begin = re.search(r'begin="([^"]+)"', s_attrs, flags=re.IGNORECASE)
                m_s_end = re.search(r'end="([^"]+)"', s_attrs, flags=re.IGNORECASE)
                
                s_begin = parse_tiempo_str(m_s_begin.group(1)) if m_s_begin else p_begin
                s_end = parse_tiempo_str(m_s_end.group(1)) if m_s_end else None
                
                if s_clean:
                    full_text_parts.append(s_clean)
                    words_list.append({
                        "time": round(s_begin, 3),
                        "endTime": round(s_end, 3) if s_end else None,
                        "text": s_clean
                    })
            for w_idx in range(len(words_list)):
                if words_list[w_idx]["endTime"] is None:
                    if w_idx + 1 < len(words_list):
                        words_list[w_idx]["endTime"] = words_list[w_idx + 1]["time"]
                    else:
                        words_list[w_idx]["endTime"] = round(p_end, 3) if p_end else round(words_list[w_idx]["time"] + 1.2, 3)
            full_text = "".join(full_text_parts).strip()
        else:
            clean_txt = re.sub(r'<[^>]+>', ' ', p_content).strip()
            clean_txt = clean_txt.replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            full_text = clean_txt
            
        if not full_text or full_text in {"…", "...", "&#x2026;"}:
            full_text = "…"
            words_list = []
            
        m_agent = re.search(r'ttm:agent="([^"]+)"', p_attrs, flags=re.IGNORECASE)
        agent = m_agent.group(1).strip() if m_agent else "v1"

        item_obj = {
            "time": round(p_begin, 3),
            "endTime": round(p_end, 3) if p_end else None,
            "text": full_text,
            "words": words_list,
            "agent": agent
        }
        lineas.append(enriquecer_adlibs(item_obj))
        
    lineas.sort(key=lambda x: x["time"])

    for i, item in enumerate(lineas):
        if item.get("endTime") is None or item["endTime"] <= item["time"]:
            if i + 1 < len(lineas):
                item["endTime"] = lineas[i + 1]["time"]
            else:
                item["endTime"] = round(item["time"] + 3.5, 3)

    # Procesar intros y pausas
    procesadas = []
    if lineas and lineas[0]["time"] > 3.0 and lineas[0]["text"] != "…":
        procesadas.append({"time": 0.0, "endTime": lineas[0]["time"], "text": "…", "words": [], "has_adlib": False})
        
    for i, item in enumerate(lineas):
        procesadas.append(item)
        if i < len(lineas) - 1:
            next_b = lineas[i + 1]["time"]
            fin_verso = item["endTime"] if (item["endTime"] and item["endTime"] > item["time"]) else item["time"] + 2.5
            pausa = next_b - fin_verso
            if pausa >= 4.5 and item["text"] != "…":
                punto_tiempo = round(fin_verso + 0.3, 3)
                if next_b - punto_tiempo >= 2.0:
                    procesadas.append({"time": punto_tiempo, "endTime": next_b, "text": "…", "words": [], "has_adlib": False})
                    
    return procesadas

def procesar_lineas_finales(lineas_raw: List[tuple]) -> List[Dict[str, Any]]:
    if not lineas_raw:
        return []

    procesadas: List[Dict[str, Any]] = []

    # 1. Intro Instrumental (> 3.0s)
    if lineas_raw[0][0] > 3.0:
        procesadas.append({"time": 0.0, "endTime": lineas_raw[0][0], "text": "…", "words": [], "has_adlib": False})

    # 2. Iterar versos y detectar silencios instrumentales reales (>= 4.5s)
    for i, (b, e, txt) in enumerate(lineas_raw):
        item_obj = {"time": round(b, 3), "endTime": round(e, 3) if e else None, "text": txt, "words": []}
        procesadas.append(enriquecer_adlibs(item_obj))

        if i < len(lineas_raw) - 1:
            next_b = lineas_raw[i + 1][0]
            fin_verso = e if (e and e > b) else b + 2.5
            pausa = next_b - fin_verso

            # Si hay una pausa instrumental real de más de 4.5s entre versos
            if pausa >= 4.5 and txt != "…":
                punto_tiempo = round(fin_verso + 0.3, 3)
                if next_b - punto_tiempo >= 2.0:
                    procesadas.append({"time": punto_tiempo, "endTime": next_b, "text": "…", "words": [], "has_adlib": False})

    return procesadas

# ============================================================
# BÚSQUEDA LRCLIB (FALLBACK ONLINE)
# ============================================================
def limpiar_texto_lrclib(texto: str) -> str:
    if not texto:
        return ""
    t = re.sub(r"\s*—.*$", "", texto)
    t = re.sub(r"\s*-\s*(Remaster|Deluxe|Bonus|Live|Mono|Stereo|Anniversary).*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\(feat\..*?\)", "", t, flags=re.IGNORECASE)
    return t.strip()

def buscar_lrclib_online(titulo: str, artista: str, duracion_seg: float = 0.0) -> Optional[List[Dict[str, Any]]]:
    headers = {"User-Agent": "NowPlaying-LocalPlayer/1.0"}
    dur_int = int(round(duracion_seg)) if duracion_seg and duracion_seg > 0 else None

    params_lista = [
        {"track_name": titulo, "artist_name": artista},
    ]
    artista_limpio = limpiar_texto_lrclib(artista)
    titulo_limpio = limpiar_texto_lrclib(titulo)
    if artista_limpio != artista or titulo_limpio != titulo:
        params_lista.append({"track_name": titulo_limpio, "artist_name": artista_limpio})

    for p in params_lista:
        if dur_int:
            p["duration"] = dur_int
        try:
            resp = requests.get("https://lrclib.net/api/get", params=p, timeout=4, headers=headers)
            if resp.status_code == 200:
                datos = resp.json()
                lrc_texto = datos.get("syncedLyrics")
                if lrc_texto:
                    return parsear_lrc(lrc_texto)
        except Exception:
            pass

    try:
        query = f"{titulo_limpio} {artista_limpio}".strip()
        resp = requests.get("https://lrclib.net/api/search", params={"q": query}, timeout=4, headers=headers)
        if resp.status_code == 200:
            resultados = resp.json()
            if isinstance(resultados, list):
                for item in resultados:
                    lrc_texto = item.get("syncedLyrics")
                    if lrc_texto:
                        return parsear_lrc(lrc_texto)
    except Exception:
        pass

    return None

# ============================================================
# ESCANEO RECURSIVO DE ARCHIVOS & METADATOS
# ============================================================
def escanear_directorio_musica(ruta_base: str):
    global biblioteca_tracks, biblioteca_folders, tracks_by_id, CACHE_LETRAS
    biblioteca_tracks = []
    biblioteca_folders = []
    tracks_by_id = {}
    CACHE_LETRAS = {}
    CACHE_COVERS_MEM.clear()

    if not os.path.exists(ruta_base):
        print(f"[SCAN] Ruta no encontrada: {ruta_base}")
        return

    print(f"[SCAN] Escaneando biblioteca en: {ruta_base} ...")
    carpetas_set = set()
    track_id_counter = 1

    for root, dirs, files in os.walk(ruta_base):
        rel_dir = os.path.relpath(root, ruta_base)
        if rel_dir == ".":
            rel_dir = ""
        carpetas_set.add(rel_dir)

        # Detección de portadas animadas en la carpeta del álbum (tall y square)
        posibles_tall = ["tall_animated_artwork.mp4", "tall_animated_artwork.m4v", "tall_animated_artwork.mov"]
        posibles_square = ["square_animated_artwork.mp4", "square_animated_artwork.m4v", "square_animated_artwork.mov"]
        folder_tall_path = None
        for pt in posibles_tall:
            p_full = os.path.join(root, pt)
            if os.path.exists(p_full):
                folder_tall_path = p_full
                break
        folder_square_path = None
        for ps in posibles_square:
            p_full = os.path.join(root, ps)
            if os.path.exists(p_full):
                folder_square_path = p_full
                break

        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in EXTS_AUDIO:
                full_path = os.path.join(root, f)
                base_name = os.path.splitext(f)[0]

                # 1. Detectar archivos de letras locales (.ttml o .lrc)
                lrc_path = None
                ttml_path = None
                lyrics_type = "none"

                posibles_ttml = [
                    os.path.join(root, f"{base_name}.ttml"),
                    os.path.join(root, f"{base_name}.TTML"),
                    os.path.join(root, f"{base_name}.xml"),
                ]
                posibles_lrc = [
                    os.path.join(root, f"{base_name}.lrc"),
                    os.path.join(root, f"{base_name}.LRC"),
                ]

                for p in posibles_ttml:
                    if os.path.exists(p):
                        ttml_path = p
                        lyrics_type = "ttml"
                        break

                for p in posibles_lrc:
                    if os.path.exists(p):
                        lrc_path = p
                        if lyrics_type == "none":
                            lyrics_type = "lrc"
                        break

                # 2. Extraer metadatos con Mutagen
                title = base_name
                artist = "Desconocido"
                album_artist = ""
                album = "Desconocido"
                genre = ""
                year = ""
                composer = ""
                track_number = 0
                disc_number = 1
                duration = 0.0
                has_embedded_cover = False
                has_embedded_lyrics = False
                is_explicit = False
                is_atmos = False
                is_lossless = False
                bitrate = 0
                sample_rate = 0
                codec = ext.lstrip(".").lower()

                if mutagen:
                    try:
                        audio_meta = mutagen.File(full_path)
                        if audio_meta:
                            duration = getattr(audio_meta.info, "length", 0.0)
                            bitrate = getattr(audio_meta.info, "bitrate", 0) or 0
                            sample_rate = getattr(audio_meta.info, "sample_rate", 0) or 0
                            codec = getattr(audio_meta.info, "codec", "") or type(audio_meta.info).__name__.lower()

                            if isinstance(audio_meta, MP4):
                                # Tags M4A/MP4
                                if "©nam" in audio_meta and audio_meta["©nam"]:
                                    title = str(audio_meta["©nam"][0])
                                if "aART" in audio_meta and audio_meta["aART"]:
                                    album_artist = str(audio_meta["aART"][0])
                                if "©ART" in audio_meta and audio_meta["©ART"]:
                                    artist = str(audio_meta["©ART"][0])
                                elif album_artist:
                                    artist = album_artist
                                if "©alb" in audio_meta and audio_meta["©alb"]:
                                    album = str(audio_meta["©alb"][0])
                                if "©gen" in audio_meta and audio_meta["©gen"]:
                                    genre = str(audio_meta["©gen"][0])
                                elif "gnre" in audio_meta and audio_meta["gnre"]:
                                    genre = str(audio_meta["gnre"][0])
                                if "©day" in audio_meta and audio_meta["©day"]:
                                    y_raw = str(audio_meta["©day"][0])
                                    year = y_raw[:4] if len(y_raw) >= 4 else y_raw
                                comp = audio_meta.get("©wrt") or audio_meta.get("\xa9wrt") or audio_meta.get("composer")
                                if comp:
                                    composer = formatear_compositores(comp)
                                if "trkn" in audio_meta and audio_meta["trkn"]:
                                    try:
                                        track_number = int(audio_meta["trkn"][0][0])
                                    except Exception:
                                        pass
                                if "disk" in audio_meta and audio_meta["disk"]:
                                    try:
                                        disc_number = int(audio_meta["disk"][0][0])
                                    except Exception:
                                        pass
                                if "covr" in audio_meta and audio_meta["covr"]:
                                    has_embedded_cover = True
                                if "©lyr" in audio_meta and audio_meta["©lyr"]:
                                    has_embedded_lyrics = True
                                    if lyrics_type == "none":
                                        lyrics_type = "embedded"
                                    lyr_str = str(audio_meta["©lyr"][0])
                                    sw = re.findall(r'<songwriter>(.*?)</songwriter>', lyr_str, flags=re.IGNORECASE)
                                    if sw:
                                        clean_sw = [s.strip() for s in sw if s.strip()]
                                        if clean_sw:
                                            composer = ", ".join(clean_sw)
                                # Rating / Explicit de iTunes (rtng: 1 = Explicit, 2 = Clean)
                                rtng = audio_meta.get("rtng")
                                if rtng and (rtng == [1] or rtng[0] == 1 or rtng == b'\x01'):
                                    is_explicit = True
                            elif hasattr(audio_meta, "tags") and audio_meta.tags:
                                tags = audio_meta.tags
                                # MP3 ID3 / FLAC / Vorbis
                                if hasattr(tags, "get"):
                                    t = tags.get("TIT2") or tags.get("TITLE")
                                    if t: title = str(t)
                                    a = tags.get("TPE1") or tags.get("ARTIST")
                                    if a: artist = str(a)
                                    alb_a = tags.get("TPE2") or tags.get("ALBUMARTIST") or tags.get("ALBUM ARTIST") or tags.get("aART")
                                    if alb_a: album_artist = str(alb_a)
                                    alb = tags.get("TALB") or tags.get("ALBUM")
                                    if alb: album = str(alb)
                                    gen = tags.get("TCON") or tags.get("GENRE")
                                    if gen: genre = str(gen)
                                    comp = tags.get("TCOM") or tags.get("COMPOSER") or tags.get("WRITER") or tags.get("TXXX:composer")
                                    if comp:
                                        composer = formatear_compositores(comp)
                                    day = tags.get("TDRC") or tags.get("TYER") or tags.get("DATE")
                                    if day:
                                        d_raw = str(day)
                                        year = d_raw[:4] if len(d_raw) >= 4 else d_raw
                                    trck = tags.get("TRCK") or tags.get("TRACKNUMBER")
                                    if trck:
                                        try:
                                            track_number = int(str(trck).split("/")[0])
                                        except Exception:
                                            pass
                                    disc = tags.get("TPOS") or tags.get("DISCNUMBER") or tags.get("DISC")
                                    if disc:
                                        try:
                                            disc_number = int(str(disc).split("/")[0])
                                        except Exception:
                                            pass
                                    advisory = tags.get("TXXX:ITUNESADVISORY") or tags.get("ITUNESADVISORY") or tags.get("ITUNES_ADVISORY")
                                    if advisory and str(advisory).strip() in {"1", "explicit", "Explicit"}:
                                        is_explicit = True
                                # Cover
                                if hasattr(tags, "getall") and tags.getall("APIC"):
                                    has_embedded_cover = True
                                if hasattr(audio_meta, "pictures") and audio_meta.pictures:
                                    has_embedded_cover = True
                    except Exception as e:
                        print(f"[SCAN] Error leyendo tags de {f}: {e}")

                # Fallback: extraer número de pista del inicio del nombre del archivo si track_number es 0
                if track_number == 0:
                    m_fn_num = re.match(r"^(\d{1,3})[\s.-]+", f)
                    if m_fn_num:
                        try:
                            track_number = int(m_fn_num.group(1))
                        except Exception:
                            pass

                info_str = str(audio_meta.info).lower() if (audio_meta and hasattr(audio_meta, "info")) else ""
                channels = getattr(audio_meta.info, "channels", 2) if (audio_meta and hasattr(audio_meta, "info")) else 2
                bits_per_sample = getattr(audio_meta.info, "bits_per_sample", 16) if (audio_meta and hasattr(audio_meta, "info")) else 16

                # Detectar Dolby Atmos en metadatos, canales, nombre del archivo, título, álbum o carpeta
                meta_dump = (full_path + " " + title + " " + album + " " + artist + " " + codec + " " + info_str).lower()
                if channels > 2 or any(k in meta_dump for k in ["atmos", "spatial", "dolby", "eac3", "ac3", "truehd", "ac4", "multichannel", "5.1", "7.1"]):
                    is_atmos = True

                # Detectar Lossless si es FLAC, ALAC, WAV, AIFF, bits_per_sample > 16 o bitrate >= 500 kbps
                if ext in {".flac", ".wav", ".aiff", ".alac", ".dsf", ".dff"} or any(k in meta_dump for k in ["flac", "alac", "wav", "aiff", "lossless", "pcm"]) or bitrate >= 500000 or bits_per_sample > 16:
                    is_lossless = True

                # Detectar también 'explicit' en el título o en el nombre del archivo
                if re.search(r'\bexplicit\b', title, re.IGNORECASE) or re.search(r'\bexplicit\b', f, re.IGNORECASE):
                    is_explicit = True

                # Limpieza si el título tiene etiqueta explícita (ej: 'Cancion (Explicit)')
                title = re.sub(r'\s*[\(\[]\s*explicit\s*[\)\]]', '', title, flags=re.IGNORECASE).strip()

                # Limpieza si el título aún tiene número de pista (ej: '01. Cancion')
                m_tracknum = re.match(r"^\d+[\s.-]+(.*)$", title)
                if m_tracknum:
                    clean_t = m_tracknum.group(1).strip()
                    if clean_t:
                        title = clean_t

                # ID determinista y único basado en la ruta relativa del archivo dentro de la biblioteca
                rel_file_key = os.path.relpath(full_path, ruta_base).replace("\\", "/")
                track_id = hashlib.sha1(rel_file_key.encode("utf-8")).hexdigest()[:12]

                # Firma de versión para invalidar caché automáticamente si el archivo cambia o se reemplaza
                try:
                    file_stat = os.stat(full_path)
                    cover_sig = f"{int(file_stat.st_mtime)}_{file_stat.st_size}"
                except Exception:
                    cover_sig = "1"

                if ttml_path and os.path.exists(ttml_path):
                    try:
                        with open(ttml_path, "r", encoding="utf-8", errors="ignore") as f_ttml:
                            sw = re.findall(r'<songwriter>(.*?)</songwriter>', f_ttml.read(), flags=re.IGNORECASE)
                            if sw:
                                clean_sw = [s.strip() for s in sw if s.strip()]
                                if clean_sw:
                                    composer = ", ".join(clean_sw)
                    except Exception:
                        pass

                track_item = {
                    "id": track_id,
                    "filename": f,
                    "path": full_path,
                    "rel_dir": rel_dir,
                    "folder_name": os.path.basename(root) if rel_dir else "Raíz",
                    "title": title,
                    "artist": artist,
                    "album_artist": album_artist,
                    "album": album,
                    "composer": composer,
                    "genre": genre,
                    "year": year,
                    "track_number": track_number,
                    "disc_number": disc_number,
                    "duration": duration,
                    "bitrate": bitrate,
                    "sample_rate": sample_rate,
                    "codec": codec,
                    "is_atmos": is_atmos,
                    "is_lossless": is_lossless,
                    "has_embedded_cover": has_embedded_cover,
                    "lrc_path": lrc_path,
                    "ttml_path": ttml_path,
                    "lyrics_type": lyrics_type,
                    "explicit": is_explicit,
                    "cover_sig": cover_sig,
                    "cover_url": f"/api/cover/{track_id}?v={cover_sig}",
                    "cover_thumb_url": f"/api/cover/{track_id}?v={cover_sig}&size=140",
                    "cover_card_url": f"/api/cover/{track_id}?v={cover_sig}&size=360",
                    "has_animated_artwork": bool(folder_tall_path or folder_square_path),
                    "animated_tall_url": f"/api/artwork/tall/{track_id}?v={cover_sig}" if folder_tall_path else None,
                    "animated_square_url": f"/api/artwork/square/{track_id}?v={cover_sig}" if folder_square_path else None,
                    "animated_tall_path": folder_tall_path,
                    "animated_square_path": folder_square_path,
                }

                biblioteca_tracks.append(track_item)
                tracks_by_id[track_id] = track_item

    # Organizar carpetas
    carpetas_ordenadas = sorted(list(carpetas_set))
    for c in carpetas_ordenadas:
        count = sum(1 for t in biblioteca_tracks if t["rel_dir"] == c)
        biblioteca_folders.append({
            "rel_dir": c,
            "name": os.path.basename(c) if c else "Raíz",
            "track_count": count
        })

    print(f"[SCAN] Completado: {len(biblioteca_tracks)} canciones en {len(biblioteca_folders)} carpetas.")

# Escaneo inicial al arrancar
escanear_directorio_musica(config_data["music_dir"])

# ============================================================
# RUTAS DE API & STREAMING
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    if es_movil(request.headers.get("user-agent", "")) and os.path.exists(RUTA_MOVIL):
        ruta_html = RUTA_MOVIL
    else:
        ruta_html = RUTA_HTML
    if os.path.exists(ruta_html):
        with open(ruta_html, "r", encoding="utf-8") as f:
            return HTMLResponse(
                content=f.read(),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    return HTMLResponse("<h1>index.html no encontrado en la carpeta completo</h1>", status_code=404)

@app.get("/movil", response_class=HTMLResponse)
async def serve_movil():
    if os.path.exists(RUTA_MOVIL):
        with open(RUTA_MOVIL, "r", encoding="utf-8") as f:
            return HTMLResponse(
                content=f.read(),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
@app.get("/i", response_class=HTMLResponse)
@app.get("/i/index.html", response_class=HTMLResponse)
async def serve_i_folder():
    ruta = os.path.join(CARPETA_COMPLETO, "amll", "i", "index.html")
    if not os.path.exists(ruta):
        ruta = RUTA_HTML
    with open(ruta, "r", encoding="utf-8") as f:
        return HTMLResponse(
            content=f.read(),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

@app.get("/manifest.json")
async def serve_manifest():
    manifest_path = os.path.join(CARPETA_COMPLETO, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="application/manifest+json")
@app.get("/amll-bundle.iife.js")
async def serve_amll_bundle():
    for ruta in [
        os.path.join(CARPETA_COMPLETO, "amll-bundle.iife.js"),
        os.path.join(CARPETA_COMPLETO, "amll", "dist-bundle", "amll-bundle.iife.js"),
        os.path.join(CARPETA_COMPLETO, "amll", "i", "amll-bundle.iife.js")
    ]:
        if os.path.exists(ruta):
            return FileResponse(ruta, media_type="application/javascript")
    raise HTTPException(status_code=404)

@app.get("/amll.css")
async def serve_amll_css():
    for ruta in [
        os.path.join(CARPETA_COMPLETO, "amll.css"),
        os.path.join(CARPETA_COMPLETO, "amll", "dist-bundle", "amll.css"),
        os.path.join(CARPETA_COMPLETO, "amll", "i", "amll.css")
    ]:
        if os.path.exists(ruta):
            return FileResponse(ruta, media_type="text/css")
    raise HTTPException(status_code=404)

@app.get("/api/config")
async def get_config():
    return config_data

class ConfigUpdateRequest(BaseModel):
    music_dir: str

@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    dir_path = normalizar_directorio(req.music_dir)
    if not dir_path or not os.path.exists(dir_path):
        raise HTTPException(status_code=400, detail=f"La ruta no existe en tu PC: {dir_path or req.music_dir}")
    if not os.path.isdir(dir_path):
        raise HTTPException(status_code=400, detail=f"La ruta indicada no es una carpeta: {dir_path}")
    
    config_data["music_dir"] = dir_path
    guardar_config()
    await asyncio.to_thread(escanear_directorio_musica, dir_path)
    return {
        "status": "ok",
        "music_dir": dir_path,
        "total_tracks": len(biblioteca_tracks),
        "total_folders": len(biblioteca_folders)
    }

@app.get("/api/scan")
async def rescan():
    dir_path = normalizar_directorio(config_data.get("music_dir", ""))
    if dir_path and os.path.exists(dir_path):
        await asyncio.to_thread(escanear_directorio_musica, dir_path)
    return {
        "status": "ok",
        "total_tracks": len(biblioteca_tracks),
        "total_folders": len(biblioteca_folders)
    }

@app.get("/api/cache/stats")
async def get_cache_stats():
    tamano = obtener_tamano_cache_audio()
    return {
        "status": "ok",
        "audio_cache_bytes": tamano,
        "audio_cache_gb": round(tamano / (1024**3), 2),
        "max_gb": 2.0
    }

@app.post("/api/cache/clear")
async def clear_cache_endpoint():
    limpiar_cache_audio_completa()
    return {
        "status": "ok",
        "message": "Caché de audio vaciada con éxito"
    }

class QueueOrderRequest(BaseModel):
    order: List[str]

@app.post("/api/queue/order")
async def set_queue_order(req: QueueOrderRequest):
    orden_valida = [tid for tid in req.order if tid in tracks_by_id]
    config_data["queue_order"] = orden_valida
    guardar_config()
    return {"status": "ok", "total": len(orden_valida)}

@app.get("/api/library")
async def get_library():
    return {
        "music_dir": config_data["music_dir"],
        "folders": biblioteca_folders,
        "queue_order": config_data.get("queue_order", []),
        "tracks": [
            {
                "id": t["id"],
                "filename": t["filename"],
                "rel_dir": t["rel_dir"],
                "folder_name": t["folder_name"],
                "title": t["title"],
                "artist": t["artist"],
                "album_artist": t.get("album_artist", ""),
                "album": t["album"],
                "genre": t.get("genre", ""),
                "year": t.get("year", ""),
                "track_number": t.get("track_number", 0),
                "disc_number": t.get("disc_number", 1),
                "duration": t["duration"],
                "bitrate": t.get("bitrate", 0),
                "sample_rate": t.get("sample_rate", 0),
                "codec": t.get("codec", ""),
                "is_atmos": t.get("is_atmos", False),
                "is_lossless": t.get("is_lossless", False),
                "path": t.get("path", ""),
                "lyrics_type": t["lyrics_type"],
                "explicit": t.get("explicit", False),
                "composer": t.get("composer", ""),
                "cover_url": t.get("cover_url", f"/api/cover/{t['id']}"),
                "cover_thumb_url": t.get("cover_thumb_url", f"/api/cover/{t['id']}?size=140"),
                "cover_card_url": t.get("cover_card_url", f"/api/cover/{t['id']}?size=360"),
                "cover_sig": t.get("cover_sig", ""),
                "has_animated_artwork": t.get("has_animated_artwork", False),
                "animated_tall_url": t.get("animated_tall_url"),
                "animated_square_url": t.get("animated_square_url"),
            }
            for t in biblioteca_tracks
        ]
    }

@app.get("/api/track/{track_id}")
async def get_track_detail(track_id: str):
    track = tracks_by_id.get(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Pista no encontrada")
    
    # Obtener letras locales de inmediato (< 1ms). Si no hay locales, devuelve [] para iniciar reproducción al instante
    lyrics = await get_lyrics_for_track(track, allow_online=False)
    
    has_word_sync = False
    for line in lyrics:
        if line.get("words") and len(line["words"]) > 0:
            has_word_sync = True
            break
        if line.get("has_adlib"):
            if (line.get("main", {}).get("words") and len(line["main"]["words"]) > 0) or \
               (line.get("adlib", {}).get("words") and len(line["adlib"]["words"]) > 0):
                has_word_sync = True
                break

    res_track = dict(track)
    res_track.update({
        "duration_ms": int(track["duration"] * 1000),
        "audio_url": f"/api/audio/{track['id']}",
        "composer": track.get("composer", ""),
        "cover_url": track.get("cover_url", f"/api/cover/{track['id']}"),
        "cover_thumb_url": track.get("cover_thumb_url", f"/api/cover/{track['id']}?size=140"),
        "cover_card_url": track.get("cover_card_url", f"/api/cover/{track['id']}?size=360"),
        "has_animated_artwork": track.get("has_animated_artwork", False),
        "animated_tall_url": track.get("animated_tall_url"),
        "animated_square_url": track.get("animated_square_url"),
        "lyrics": lyrics,
        "lyrics_type": track["lyrics_type"] if lyrics else "none",
        "has_word_sync": has_word_sync,
        "explicit": track.get("explicit", False),
        "raw_ttml": track.get("raw_ttml", ""),
        "raw_lrc": track.get("raw_lrc", ""),
    })
    return res_track

@app.get("/api/enrichment")
async def get_enrichment(album: Optional[str] = None, artist: Optional[str] = None, title: Optional[str] = None):
    """
    Endpoint de enriquecimiento para clientes móviles (Minidisc / iOS).
    Permite encontrar portadas animadas (.mp4 square y tall), letras TTML e indicador Dolby Atmos
    mediante búsqueda rápida por coincidencia de álbum, artista o título.
    """
    if not biblioteca_tracks:
        return {"found": False}

    norm_album = (album or "").strip().lower()
    norm_artist = (artist or "").strip().lower()
    norm_title = (title or "").strip().lower()

    best_match = None
    best_score = 0

    for t in biblioteca_tracks:
        score = 0
        t_album = t.get("album", "").strip().lower()
        t_artist = t.get("artist", "").strip().lower()
        t_title = t.get("title", "").strip().lower()

        if norm_album and (norm_album == t_album or norm_album in t_album or t_album in norm_album):
            score += 10
        if norm_artist and (norm_artist == t_artist or norm_artist in t_artist or t_artist in norm_artist):
            score += 5
        if norm_title and (norm_title == t_title or norm_title in t_title or t_title in norm_title):
            score += 10

        if score > best_score:
            best_score = score
            best_match = t

    if best_match and best_score >= 5:
        return {
            "found": True,
            "track_id": best_match["id"],
            "title": best_match["title"],
            "artist": best_match["artist"],
            "album": best_match["album"],
            "has_animated_artwork": best_match.get("has_animated_artwork", False),
            "animated_square_url": best_match.get("animated_square_url"),
            "animated_tall_url": best_match.get("animated_tall_url"),
            "is_atmos": best_match.get("is_atmos", False),
            "is_lossless": best_match.get("is_lossless", False),
            "lyrics_url": f"/api/lyrics/{best_match['id']}",
            "lyrics_type": best_match.get("lyrics_type", "none")
        }

    return {"found": False}

@app.get("/api/lyrics/{track_id}")
async def get_track_lyrics(track_id: str):
    track = tracks_by_id.get(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Pista no encontrada")
    lyrics = await get_lyrics_for_track(track, allow_online=True)
    has_word_sync = False
    for line in lyrics:
        if line.get("words") and len(line["words"]) > 0:
            has_word_sync = True
            break
        if line.get("has_adlib"):
            if (line.get("main", {}).get("words") and len(line["main"]["words"]) > 0) or \
               (line.get("adlib", {}).get("words") and len(line["adlib"]["words"]) > 0):
                has_word_sync = True
                break
    return {
        "lyrics": lyrics,
        "lyrics_type": track["lyrics_type"] if lyrics else "none",
        "has_word_sync": has_word_sync,
        "composer": track.get("composer", ""),
        "raw_ttml": track.get("raw_ttml", ""),
        "raw_lrc": track.get("raw_lrc", "")
    }

async def get_lyrics_for_track(track: Dict[str, Any], allow_online: bool = True) -> List[Dict[str, Any]]:
    track_id = track["id"]
    if track_id in CACHE_LETRAS:
        return CACHE_LETRAS[track_id]

    # 1. Archivo .ttml local (Prioridad máxima por soporte de Karaoke y Adlibs)
    if track.get("ttml_path") and os.path.exists(track["ttml_path"]):
        try:
            with open(track["ttml_path"], "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                track["raw_ttml"] = content
                sw = re.findall(r'<songwriter>(.*?)</songwriter>', content, flags=re.IGNORECASE)
                if sw:
                    clean_sw = [s.strip() for s in sw if s.strip()]
                    if clean_sw:
                        track["composer"] = ", ".join(clean_sw)
                parsed = parsear_ttml(content)
                if parsed:
                    CACHE_LETRAS[track_id] = parsed
                    return parsed
        except Exception as e:
            print(f"[LETRA] Error leyendo TTML local: {e}")

    # 2. Archivo .lrc local
    if track.get("lrc_path") and os.path.exists(track["lrc_path"]):
        try:
            with open(track["lrc_path"], "r", encoding="utf-8", errors="ignore") as f:
                lrc_content = f.read()
                track["raw_lrc"] = lrc_content
                parsed = parsear_lrc(lrc_content)
                if parsed:
                    CACHE_LETRAS[track_id] = parsed
                    return parsed
        except Exception as e:
            print(f"[LETRA] Error leyendo LRC local: {e}")

    # 3. Letras embebidas en el archivo .m4a / .mp3
    if mutagen and os.path.exists(track["path"]):
        try:
            audio_meta = mutagen.File(track["path"])
            if isinstance(audio_meta, MP4) and "©lyr" in audio_meta and audio_meta["©lyr"]:
                txt = str(audio_meta["©lyr"][0])
                sw = re.findall(r'<songwriter>(.*?)</songwriter>', txt, flags=re.IGNORECASE)
                if sw:
                    clean_sw = [s.strip() for s in sw if s.strip()]
                    if clean_sw:
                        track["composer"] = ", ".join(clean_sw)
                if "<tt" in txt or "<p " in txt:
                    track["raw_ttml"] = txt
                    parsed = parsear_ttml(txt)
                elif "[" in txt:
                    track["raw_lrc"] = txt
                    parsed = parsear_lrc(txt)
                else:
                    parsed = [{"time": 0.0, "text": linea.strip()} for linea in txt.splitlines() if linea.strip()]
                if parsed:
                    CACHE_LETRAS[track_id] = parsed
                    return parsed
        except Exception as e:
            print(f"[LETRA] Error leyendo letra embebida: {e}")

    # 4. Fallback LRCLIB Online solo cuando se permite explícitamente (en segundo plano)
    if allow_online:
        parsed_online = await asyncio.to_thread(buscar_lrclib_online, track["title"], track["artist"], track["duration"])
        if parsed_online:
            CACHE_LETRAS[track_id] = parsed_online
            return parsed_online
        CACHE_LETRAS[track_id] = []
        return []

    return []

# ============================================================
# STREAMING DE AUDIO CON SOPORTE HTTP RANGE Y FLAC BIT-PERFECT
# ============================================================
def cliente_soporta_alac_nativo(request: Request) -> bool:
    """Detecta si el cliente tiene soporte nativo de ALAC / EC-3 en contenedor MP4 (iOS / Safari / macOS Safari)."""
    format_param = request.query_params.get("format", "").lower()
    if format_param == "flac":
        return False
    if format_param == "original":
        return True
    ua = (request.headers.get("user-agent") or "").lower()
    # iOS, iPadOS, tvOS, macOS y AVPlayer nativo (AppleCoreMedia/CFNetwork) decodifican ALAC y Dolby Atmos/EC-3 por hardware
    if "iphone" in ua or "ipad" in ua or "ipod" in ua or "applecoremedia" in ua or "appletv" in ua or "darwin" in ua or "cfnetwork" in ua:
        return True
    # macOS Safari puro
    if "macintosh" in ua and "safari" in ua and "chrome" not in ua and "edg" not in ua and "firefox" not in ua:
        return True
    # En Windows (Chrome, Edge, Firefox), Android y Linux, HTML5 <audio> no soporta ALAC ni EC-3
    return False

def convertir_a_flac(src_path: str, dst_cache_path: str, codec: str, modo: str = "5.1"):
    """
    Convierte pistas ALAC (lossless) o EC-3/Atmos a FLAC de máxima fidelidad.
    - ALAC: Conversión 100% bit-perfect lossless.
    - EC-3/Atmos modo '5.1': Preserva los 6 canales discretos íntegros a 24-bit 48kHz (surround 5.1 real).
    - EC-3/Atmos modo 'stereo': Downmix estéreo balanceado a 48kHz (-ac 2).
    """
    temp_dst = dst_cache_path + ".tmp"
    try:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src_path, "-vn"]
        is_atmos_track = (codec in ("ec-3", "eac3") or "atmos" in (codec or "").lower())
        if is_atmos_track and modo == "stereo":
            cmd.extend(["-ac", "2"])
        # compression_level 0 es 100% lossless bit-perfect y codifica a máxima velocidad
        cmd.extend(["-c:a", "flac", "-compression_level", "0", "-f", "flac", temp_dst])
        subprocess.run(cmd, check=True)
        if os.path.exists(temp_dst) and os.path.getsize(temp_dst) > 0:
            os.replace(temp_dst, dst_cache_path)
    except Exception as e:
        print(f"[AUDIO CONVERT] Error convirtiendo {src_path} a FLAC ({modo}): {e}")
        if os.path.exists(temp_dst):
            try:
                os.remove(temp_dst)
            except Exception:
                pass
        raise


CORS_AUDIO_HEADERS = {
    "Accept-Ranges": "bytes",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
    "Cache-Control": "public, max-age=3600",
}

@app.get("/api/audio/preload/{track_id}")
async def preload_audio(track_id: str, request: Request):
    """Pre-transcodifica pistas en segundo plano en el modo deseado (5.1 o stereo)."""
    track = tracks_by_id.get(track_id)
    if not track or not os.path.exists(track["path"]):
        return {"status": "not_found"}
    codec = (track.get("codec") or "").lower()
    is_atmos_track = (codec in ("ec-3", "eac3") or track.get("is_atmos", False))

    mode_param = (request.query_params.get("mode") or "").lower()
    modo_atmos = "stereo" if mode_param in ("stereo", "2ch", "2") else "5.1"

    if codec in ("alac", "ec-3", "eac3") or is_atmos_track:
        cover_sig = track.get("cover_sig", "1")
        if is_atmos_track:
            cache_suffix = "51" if modo_atmos == "5.1" else "stereo"
            cache_file = os.path.join(DIR_CACHE_AUDIO, f"{track_id}_{cover_sig}_{cache_suffix}.flac")
            lock_key = f"{track_id}_{cache_suffix}"
        else:
            cache_file = os.path.join(DIR_CACHE_AUDIO, f"{track_id}_{cover_sig}_lossless.flac")
            if not os.path.exists(cache_file):
                legacy_file = os.path.join(DIR_CACHE_AUDIO, f"{track_id}_{cover_sig}.flac")
                if os.path.exists(legacy_file) and os.path.getsize(legacy_file) > 0:
                    cache_file = legacy_file
            lock_key = f"{track_id}_lossless"

        if not (os.path.exists(cache_file) and os.path.getsize(cache_file) > 0):
            if lock_key not in AUDIO_LOCKS:
                AUDIO_LOCKS[lock_key] = asyncio.Lock()
            async with AUDIO_LOCKS[lock_key]:
                if not (os.path.exists(cache_file) and os.path.getsize(cache_file) > 0):
                    await asyncio.to_thread(limpiar_lru_cache_audio, 150 * 1024 * 1024)
                    await asyncio.to_thread(convertir_a_flac, track["path"], cache_file, codec, modo_atmos)
            return {"status": "cached", "mode": modo_atmos}
    return {"status": "already_ready"}

@app.get("/api/audio/{track_id}")
async def stream_audio(track_id: str, request: Request):
    track = tracks_by_id.get(track_id)
    if not track or not os.path.exists(track["path"]):
        raise HTTPException(status_code=404, detail="Audio no encontrado")

    src_path = track["path"]
    codec = (track.get("codec") or "").lower()
    ext = os.path.splitext(src_path)[1].lower()
    is_atmos_track = (codec in ("ec-3", "eac3") or track.get("is_atmos", False))

    # Parámetro de modo: '5.1' (o 'atmos') para multicanal íntegro, 'stereo' para 2 canales
    mode_param = (request.query_params.get("mode") or "").lower()
    modo_atmos = "stereo" if mode_param in ("stereo", "2ch", "2") else "5.1"

    # Detectar si se requiere FLAC para navegadores sin soporte nativo de ALAC / EC-3 (Chrome/Edge/Firefox en PC y Android)
    needs_flac = False
    if codec in ("alac", "ec-3", "eac3") or is_atmos_track:
        if not cliente_soporta_alac_nativo(request):
            needs_flac = True

    target_file = src_path
    content_type = "audio/mp4"

    if needs_flac:
        cover_sig = track.get("cover_sig", "1")
        if is_atmos_track:
            cache_suffix = "51" if modo_atmos == "5.1" else "stereo"
            cache_file = os.path.join(DIR_CACHE_AUDIO, f"{track_id}_{cover_sig}_{cache_suffix}.flac")
            lock_key = f"{track_id}_{cache_suffix}"
        else:
            cache_file = os.path.join(DIR_CACHE_AUDIO, f"{track_id}_{cover_sig}_lossless.flac")
            if not os.path.exists(cache_file):
                legacy_file = os.path.join(DIR_CACHE_AUDIO, f"{track_id}_{cover_sig}.flac")
                if os.path.exists(legacy_file) and os.path.getsize(legacy_file) > 0:
                    cache_file = legacy_file
            lock_key = f"{track_id}_lossless"

        # Garantizar archivo completo en disco para soporte nativo de HTTP 206 Range y seek fluido
        if not (os.path.exists(cache_file) and os.path.getsize(cache_file) > 0):
            if lock_key not in AUDIO_LOCKS:
                AUDIO_LOCKS[lock_key] = asyncio.Lock()
            async with AUDIO_LOCKS[lock_key]:
                if not (os.path.exists(cache_file) and os.path.getsize(cache_file) > 0):
                    await asyncio.to_thread(limpiar_lru_cache_audio, 150 * 1024 * 1024)
                    await asyncio.to_thread(convertir_a_flac, src_path, cache_file, codec, modo_atmos)

        target_file = cache_file
        content_type = "audio/flac"

        # Actualizar fecha de acceso para la política LRU (evita que se purgue la canción activa)
        try:
            os.utime(target_file, None)
        except Exception:
            pass
    else:
        mime_types = {
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".flac": "audio/flac",
            ".wav": "audio/wav",
            ".aac": "audio/aac",
            ".ogg": "audio/ogg",
            ".opus": "audio/opus",
        }
        content_type = mime_types.get(ext, "application/octet-stream")

    file_size = os.path.getsize(target_file)
    range_header = request.headers.get("range")
    if range_header:
        range_match = re.match(r"bytes=(\d+)-(\d+)?", range_header)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            start = max(0, min(start, file_size - 1))
            end = max(start, min(end, file_size - 1))
            content_length = end - start + 1

            def iter_file():
                with open(target_file, "rb") as f:
                    f.seek(start)
                    bytes_left = content_length
                    chunk_size = 256 * 1024  # 256 KB para streaming ultra suave
                    while bytes_left > 0:
                        read_size = min(chunk_size, bytes_left)
                        data = f.read(read_size)
                        if not data:
                            break
                        bytes_left -= len(data)
                        yield data

            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
                "Content-Type": content_type,
                **CORS_AUDIO_HEADERS
            }
            return StreamingResponse(iter_file(), status_code=206, headers=headers)

    headers = {
        **CORS_AUDIO_HEADERS
    }
    return FileResponse(target_file, media_type=content_type, headers=headers)

# ============================================================
# EXTRACCIÓN Y SERVIDO DE CARÁTULAS CON CACHÉ ULTRA RÁPIDO
# ============================================================
def obtener_bytes_portada_original(track_id: str, track: dict, cover_sig: str) -> Optional[tuple]:
    """Obtiene (data_bytes, mime) de la carátula original desde RAM, disco o extracción."""
    # 0a. Caché en memoria RAM validando la firma
    if track_id in CACHE_COVERS_MEM:
        cached_sig, data_bytes, mime = CACHE_COVERS_MEM[track_id]
        if cached_sig == cover_sig:
            return data_bytes, mime

    # 0b. Caché en disco original
    cache_path_jpg = os.path.join(DIR_CACHE_COVERS, f"{track_id}_{cover_sig}.jpg")
    cache_path_png = os.path.join(DIR_CACHE_COVERS, f"{track_id}_{cover_sig}.png")
    if os.path.exists(cache_path_jpg):
        try:
            with open(cache_path_jpg, "rb") as f:
                data = f.read()
                return data, "image/jpeg"
        except Exception:
            pass
    if os.path.exists(cache_path_png):
        try:
            with open(cache_path_png, "rb") as f:
                data = f.read()
                return data, "image/png"
        except Exception:
            pass

    # 1. Extracción desde audio embebido
    file_path = track["path"]
    folder_path = os.path.dirname(file_path)
    if mutagen and os.path.exists(file_path):
        try:
            audio_meta = mutagen.File(file_path)
            if isinstance(audio_meta, MP4) and "covr" in audio_meta and audio_meta["covr"]:
                cover_data = audio_meta["covr"][0]
                is_png = getattr(cover_data, "imageformat", None) == MP4Cover.FORMAT_PNG
                mime = "image/png" if is_png else "image/jpeg"
                data_bytes = bytes(cover_data)
                save_path = cache_path_png if is_png else cache_path_jpg
                try:
                    with open(save_path, "wb") as f:
                        f.write(data_bytes)
                except Exception:
                    pass
                if len(CACHE_COVERS_MEM) < 150:
                    CACHE_COVERS_MEM[track_id] = (cover_sig, data_bytes, mime)
                return data_bytes, mime
            elif hasattr(audio_meta, "tags") and audio_meta.tags:
                tags = audio_meta.tags
                if hasattr(tags, "getall"):
                    apics = tags.getall("APIC")
                    if apics:
                        apic = apics[0]
                        mime = getattr(apic, "mime", "image/jpeg")
                        is_png = "png" in mime.lower()
                        data_bytes = bytes(apic.data)
                        save_path = cache_path_png if is_png else cache_path_jpg
                        try:
                            with open(save_path, "wb") as f:
                                f.write(data_bytes)
                        except Exception:
                            pass
                        if len(CACHE_COVERS_MEM) < 150:
                            CACHE_COVERS_MEM[track_id] = (cover_sig, data_bytes, mime)
                        return data_bytes, mime
            if hasattr(audio_meta, "pictures") and audio_meta.pictures:
                pic = audio_meta.pictures[0]
                mime = pic.mime or "image/jpeg"
                is_png = "png" in mime.lower()
                data_bytes = bytes(pic.data)
                save_path = cache_path_png if is_png else cache_path_jpg
                try:
                    with open(save_path, "wb") as f:
                        f.write(data_bytes)
                except Exception:
                    pass
                if len(CACHE_COVERS_MEM) < 150:
                    CACHE_COVERS_MEM[track_id] = (cover_sig, data_bytes, mime)
                return data_bytes, mime
        except Exception as e:
            print(f"[COVER] Error leyendo carátula embebida: {e}")

    # 2. Imagen en la misma carpeta
    nombres_portada = ["cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "front.png", "album.jpg", "art.jpg"]
    for nombre in nombres_portada:
        p = os.path.join(folder_path, nombre)
        if os.path.exists(p):
            mime = "image/png" if p.lower().endswith(".png") else "image/jpeg"
            try:
                with open(p, "rb") as f:
                    data = f.read()
                    return data, mime
            except Exception:
                pass

    return None

@app.get("/api/cover/{track_id}")
def get_cover(track_id: str, request: Request, v: Optional[str] = None, size: Optional[int] = None):
    track = tracks_by_id.get(track_id)
    if not track or not os.path.exists(track["path"]):
        raise HTTPException(status_code=404, detail="Pista no encontrada")

    cover_sig = track.get("cover_sig", "")
    target_size = None
    if size is not None:
        try:
            target_size = min(1024, max(48, int(size)))
        except (ValueError, TypeError):
            target_size = None

    thumb_sig = f"{cover_sig}_s{target_size}" if target_size else cover_sig
    etag_val = f'"{thumb_sig}"' if thumb_sig else f'"{track_id}"'
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Cache-Control": "public, max-age=86400, stale-while-revalidate=86400",
        "ETag": etag_val,
    }

    # Validación ETag HTTP 304 Not Modified
    req_etag = request.headers.get("if-none-match", "").strip('"')
    if thumb_sig and req_etag == thumb_sig:
        return Response(status_code=304, headers=cors_headers)

    # Si se pide miniatura y ya existe en el disco, responder de inmediato
    if target_size:
        cache_path_thumb = os.path.join(DIR_CACHE_COVERS, f"{track_id}_{cover_sig}_s{target_size}.jpg")
        if os.path.exists(cache_path_thumb):
            return FileResponse(cache_path_thumb, media_type="image/jpeg", headers=cors_headers)

    # Obtener bytes de la carátula original
    res = obtener_bytes_portada_original(track_id, track, cover_sig)
    if not res:
        raise HTTPException(status_code=404, detail="Carátula no encontrada")

    data_bytes, mime = res

    # Si se solicitó miniatura, redimensionar y guardar en caché
    if target_size:
        thumb_bytes = redimensionar_imagen_bytes(data_bytes, target_size)
        if thumb_bytes:
            cache_path_thumb = os.path.join(DIR_CACHE_COVERS, f"{track_id}_{cover_sig}_s{target_size}.jpg")
            try:
                with open(cache_path_thumb, "wb") as f_thumb:
                    f_thumb.write(thumb_bytes)
            except Exception:
                pass
            return Response(content=thumb_bytes, media_type="image/jpeg", headers=cors_headers)

    # Sin parámetro de tamaño: Devolver carátula original 100% full-resolution
    return Response(content=data_bytes, media_type=mime, headers=cors_headers)

@app.get("/api/artwork/{artwork_type}/{track_id}")
async def get_animated_artwork(artwork_type: str, track_id: str, request: Request, v: Optional[str] = None):
    track = tracks_by_id.get(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Pista no encontrada")

    art_type = artwork_type.lower().strip()
    if art_type == "tall":
        video_path = track.get("animated_tall_path")
    elif art_type == "square":
        video_path = track.get("animated_square_path")
    else:
        raise HTTPException(status_code=400, detail="Tipo de arte animado inválido ('tall' o 'square')")

    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Arte animado no disponible para este álbum")

    file_size = os.path.getsize(video_path)
    cover_sig = track.get("cover_sig", "")
    etag_val = f'"{cover_sig}_{art_type}"' if cover_sig else f'"{track_id}_{art_type}"'

    cors_video_headers = {
        "Accept-Ranges": "bytes",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
        "Cache-Control": "public, max-age=604800, immutable",
        "ETag": etag_val,
    }

    # Validación ETag HTTP 304 Not Modified
    req_etag = request.headers.get("if-none-match", "").strip('"')
    if cover_sig and req_etag == f"{cover_sig}_{art_type}":
        return Response(status_code=304, headers=cors_video_headers)

    range_header = request.headers.get("range")
    if range_header:
        range_match = re.match(r"bytes=(\d+)-(\d+)?", range_header)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            start = max(0, min(start, file_size - 1))
            end = max(start, min(end, file_size - 1))
            content_length = end - start + 1

            def iter_video():
                with open(video_path, "rb") as f:
                    f.seek(start)
                    bytes_left = content_length
                    chunk_size = 512 * 1024  # 512 KB
                    while bytes_left > 0:
                        read_size = min(chunk_size, bytes_left)
                        data = f.read(read_size)
                        if not data:
                            break
                        bytes_left -= len(data)
                        yield data

            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
                "Content-Type": "video/mp4",
                **cors_video_headers
            }
            return StreamingResponse(iter_video(), status_code=206, headers=headers)

    return FileResponse(video_path, media_type="video/mp4", headers=cors_video_headers)


def obtener_ips_locales() -> List[str]:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        principal = s.getsockname()[0]
        s.close()
        if principal and not principal.startswith("127."):
            ips.append(principal)
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips

@app.on_event("startup")
async def on_startup():
    limpiar_archivos_temporales()
    limpiar_lru_cache_audio()

@app.on_event("shutdown")
async def on_shutdown():
    limpiar_cache_audio_completa()

if __name__ == "__main__":
    ips = obtener_ips_locales()
    print("=" * 65)
    print("  REPRODUCTOR LOCAL COMPLETO - TRANSMISIÓN LOCAL")
    print("=" * 65)
    print(f"  * Carpeta de Música: {config_data['music_dir']}")
    print(f"  * Canciones encontradas: {len(biblioteca_tracks)}")
    print(f"  * Límite de Caché de Audio: 2 GB (LRU automático)")
    print("-" * 65)
    print(f"  [PC Local]        http://localhost:{PUERTO}")
    if ips:
        print("  [Celular / Red Local]:")
        for ip in ips:
            print(f"    -> http://{ip}:{PUERTO}  (o http://{ip}:{PUERTO}/movil)")
    print("-" * 65)
    print("  * Nota: Asegúrate de que el celular esté en la misma red Wi-Fi")
    print("    o conectado a la 'Zona con cobertura inalámbrica' (Hotspot) de tu PC.")
    print("=" * 65 + "\n")
    try:
        uvicorn.run("servidor_completo:app", host="0.0.0.0", port=PUERTO, reload=False)
    finally:
        limpiar_cache_audio_completa()

