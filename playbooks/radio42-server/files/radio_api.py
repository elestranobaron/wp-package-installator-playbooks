#!/usr/bin/env python3
"""
Radio 42 — API de contrôle
Pont entre le plugin WordPress et la stack MPD/Icecast/Liquidsoap
"""

import os
import logging
import xml.etree.ElementTree as ET
from functools import wraps

import requests
from flask import Flask, jsonify, request, abort
from musicpd import MPDClient, CommandError, ConnectionError as MPDConnectionError

# ── Configuration ──────────────────────────────────────────────────────────
MPD_HOST         = os.getenv("MPD_HOST", "mpd")
MPD_PORT         = int(os.getenv("MPD_PORT", 6600))
ICECAST_HOST     = os.getenv("ICECAST_HOST", "icecast")
ICECAST_PORT     = int(os.getenv("ICECAST_PORT", 8000))
ICECAST_ADMIN_PW = os.getenv("ICECAST_ADMIN_PASSWORD", "")
API_SECRET_KEY   = os.getenv("API_SECRET_KEY", "")
MUSIC_DIR        = os.getenv("MUSIC_DIR", "/music")
PLAYLISTS_DIR    = os.getenv("PLAYLISTS_DIR", "/playlists")

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/var/log/radio42/api.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("radio42.api")

# ── App Flask ──────────────────────────────────────────────────────────────
app = Flask(__name__)


# ── Authentification par token ─────────────────────────────────────────────
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()
        if not token or token != API_SECRET_KEY:
            logger.warning("Tentative d'accès non autorisée depuis %s", request.remote_addr)
            abort(401, description="Token invalide ou manquant")
        return f(*args, **kwargs)
    return decorated


# ── Connexion MPD (context manager) ───────────────────────────────────────
def get_mpd_client():
    """Retourne un client MPD connecté."""
    client = MPDClient()
    client.timeout = 10
    client.connect(MPD_HOST, MPD_PORT)
    return client


def with_mpd(f):
    """Décorateur : injecte un client MPD et le ferme proprement."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        client = None
        try:
            client = get_mpd_client()
            return f(client, *args, **kwargs)
        except MPDConnectionError as e:
            logger.error("MPD connexion échouée : %s", e)
            abort(503, description="MPD indisponible")
        except CommandError as e:
            logger.error("MPD commande échouée : %s", e)
            abort(500, description=str(e))
        finally:
            if client:
                try:
                    client.close()
                    client.disconnect()
                except Exception:
                    pass
    return wrapper


# =============================================================================
# ENDPOINTS
# =============================================================================

# ── Santé ──────────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    """Healthcheck (pas d'auth requise)."""
    return jsonify({"status": "ok", "service": "radio42-api"})


# ── Statut global ──────────────────────────────────────────────────────────
@app.route("/status", methods=["GET"])
@require_auth
@with_mpd
def status(mpd):
    """Retourne l'état complet : MPD + auditeurs Icecast."""
    mpd_status  = mpd.status()
    current     = mpd.currentsong()
    listeners   = _get_icecast_listeners()

    return jsonify({
        "state":       mpd_status.get("state", "unknown"),    # play/pause/stop
        "volume":      int(mpd_status.get("volume", 0)),
        "repeat":      mpd_status.get("repeat") == "1",
        "random":      mpd_status.get("random") == "1",
        "single":      mpd_status.get("single") == "1",
        "elapsed":     float(mpd_status.get("elapsed", 0)),
        "duration":    float(mpd_status.get("duration", 0)),
        "listeners":   listeners,
        "current_song": {
            "title":    current.get("title", ""),
            "artist":   current.get("artist", ""),
            "album":    current.get("album", ""),
            "file":     current.get("file", ""),
            "pos":      current.get("pos", ""),
            "id":       current.get("id", ""),
        } if current else None,
    })


# ── Contrôle lecture ───────────────────────────────────────────────────────
@app.route("/play", methods=["POST"])
@require_auth
@with_mpd
def play(mpd):
    mpd.play()
    return jsonify({"action": "play", "status": "ok"})


@app.route("/pause", methods=["POST"])
@require_auth
@with_mpd
def pause(mpd):
    mpd.pause()
    return jsonify({"action": "pause", "status": "ok"})


@app.route("/stop", methods=["POST"])
@require_auth
@with_mpd
def stop(mpd):
    mpd.stop()
    return jsonify({"action": "stop", "status": "ok"})


@app.route("/next", methods=["POST"])
@require_auth
@with_mpd
def next_track(mpd):
    mpd.next()
    current = mpd.currentsong()
    return jsonify({
        "action": "next",
        "current_song": {
            "title":  current.get("title", ""),
            "artist": current.get("artist", ""),
        } if current else None,
    })


@app.route("/previous", methods=["POST"])
@require_auth
@with_mpd
def previous_track(mpd):
    mpd.previous()
    current = mpd.currentsong()
    return jsonify({
        "action": "previous",
        "current_song": {
            "title":  current.get("title", ""),
            "artist": current.get("artist", ""),
        } if current else None,
    })


# ── Volume ─────────────────────────────────────────────────────────────────
@app.route("/volume", methods=["POST"])
@require_auth
@with_mpd
def set_volume(mpd):
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if level is None or not isinstance(level, (int, float)):
        abort(400, description="'level' (0-100) requis")
    level = max(0, min(100, int(level)))
    mpd.setvol(level)
    return jsonify({"action": "volume", "level": level})


# ── Modes ──────────────────────────────────────────────────────────────────
@app.route("/mode", methods=["POST"])
@require_auth
@with_mpd
def set_mode(mpd):
    data    = request.get_json(silent=True) or {}
    random  = data.get("random")
    repeat  = data.get("repeat")
    single  = data.get("single")
    if random  is not None: mpd.random(1 if random  else 0)
    if repeat  is not None: mpd.repeat(1 if repeat  else 0)
    if single  is not None: mpd.single(1 if single  else 0)
    return jsonify({"action": "mode", "random": random, "repeat": repeat, "single": single})


# ── File de lecture (queue) ────────────────────────────────────────────────
@app.route("/queue", methods=["GET"])
@require_auth
@with_mpd
def get_queue(mpd):
    return jsonify({"queue": mpd.playlistinfo()})


@app.route("/queue/clear", methods=["POST"])
@require_auth
@with_mpd
def clear_queue(mpd):
    mpd.clear()
    return jsonify({"action": "clear_queue", "status": "ok"})


@app.route("/queue/add", methods=["POST"])
@require_auth
@with_mpd
def add_to_queue(mpd):
    data = request.get_json(silent=True) or {}
    uri  = data.get("uri", "").strip().lstrip("/")
    if not uri or ".." in uri.split("/"):
        abort(400, description="'uri' requis et chemin relatif valide")
    base = os.path.realpath(MUSIC_DIR)
    target = os.path.realpath(os.path.join(MUSIC_DIR, uri))
    if os.path.commonpath([base, target]) != base:
        abort(400, description="Chemin non autorisé")
    mpd.add(uri)
    return jsonify({"action": "add", "uri": uri})


@app.route("/queue/jump/<int:pos>", methods=["POST"])
@require_auth
@with_mpd
def jump_to(mpd, pos):
    mpd.play(pos)
    return jsonify({"action": "jump", "pos": pos})


# ── Bibliothèque musicale ──────────────────────────────────────────────────
@app.route("/library", methods=["GET"])
@require_auth
@with_mpd
def get_library(mpd):
    search = request.args.get("q", "").strip()
    if search:
        results = mpd.search("any", search)
    else:
        results = mpd.listallinfo()
    # Limiter la réponse aux fichiers audio uniquement
    files = [
        {
            "file":   item["file"],
            "title":  item.get("title", ""),
            "artist": item.get("artist", ""),
            "album":  item.get("album", ""),
            "time":   item.get("time", ""),
        }
        for item in results if "file" in item
    ]
    return jsonify({"library": files, "count": len(files)})


@app.route("/library/update", methods=["POST"])
@require_auth
@with_mpd
def update_library(mpd):
    """Demande à MPD de rescanner la bibliothèque (après upload de fichiers)."""
    job_id = mpd.update()
    return jsonify({"action": "update", "job_id": job_id})


# ── Playlists ─────────────────────────────────────────────────────────────
@app.route("/playlists", methods=["GET"])
@require_auth
@with_mpd
def list_playlists(mpd):
    playlists = mpd.listplaylists()
    return jsonify({"playlists": playlists})


@app.route("/playlists/<name>/load", methods=["POST"])
@require_auth
@with_mpd
def load_playlist(mpd, name):
    mpd.clear()
    mpd.load(name)
    mpd.play()
    return jsonify({"action": "load_playlist", "name": name})


@app.route("/playlists/<name>/save", methods=["POST"])
@require_auth
@with_mpd
def save_playlist(mpd, name):
    mpd.save(name)
    return jsonify({"action": "save_playlist", "name": name})


@app.route("/playlists/<name>", methods=["DELETE"])
@require_auth
@with_mpd
def delete_playlist(mpd, name):
    mpd.rm(name)
    return jsonify({"action": "delete_playlist", "name": name})


# ── Statistiques ──────────────────────────────────────────────────────────
@app.route("/stats", methods=["GET"])
@require_auth
@with_mpd
def get_stats(mpd):
    mpd_stats = mpd.stats()
    listeners = _get_icecast_listeners()
    return jsonify({
        "listeners":    listeners,
        "songs":        int(mpd_stats.get("songs", 0)),
        "albums":       int(mpd_stats.get("albums", 0)),
        "artists":      int(mpd_stats.get("artists", 0)),
        "uptime":       int(mpd_stats.get("uptime", 0)),
        "playtime":     int(mpd_stats.get("playtime", 0)),
        "db_playtime":  int(mpd_stats.get("db_playtime", 0)),
    })


# ── Auditeurs Icecast ──────────────────────────────────────────────────────
def _get_icecast_listeners() -> int:
    """Interroge l'API XML d'Icecast pour compter les auditeurs."""
    try:
        r = requests.get(
            f"http://{ICECAST_HOST}:{ICECAST_PORT}/admin/stats",
            auth=("admin", ICECAST_ADMIN_PW),
            timeout=3,
        )
        if r.status_code == 200:
            root   = ET.fromstring(r.text)
            source = root.find(".//source[@mount='/stream']")
            if source is not None:
                listeners_el = source.find("listeners")
                if listeners_el is not None:
                    return int(listeners_el.text)
    except Exception as e:
        logger.warning("Impossible de lire les stats Icecast : %s", e)
    return 0


# ── Gestion des erreurs ────────────────────────────────────────────────────
@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(404)
@app.errorhandler(500)
@app.errorhandler(503)
def handle_error(e):
    return jsonify({"error": str(e.description)}), e.code


# ── Point d'entrée ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not API_SECRET_KEY:
        logger.critical("API_SECRET_KEY non définie — démarrage refusé")
        raise SystemExit(1)
    logger.info("Radio 42 API démarrée sur :5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
