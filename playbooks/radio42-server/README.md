# 📻 Radio 42 Server — Playbook Ansible

Déploie un serveur de diffusion radio complet **via Docker**, sans polluer l'hôte.

Conçu pour fonctionner avec le plugin WordPress **Radio Control Center**, compagnon de [Simple Radio Forty Two](https://wordpress.org/plugins/simple-radio-forty-two/).

---

## Stack déployée

| Conteneur        | Rôle                                            | Image                        |
|------------------|-------------------------------------------------|------------------------------|
| `radio42_icecast`| Serveur de streaming public (HTTP/Icecast)      | `libretime/icecast`          |
| `radio42_mpd`    | Lecteur audio + gestion bibliothèque            | `viranch/mpd`                |
| `radio42_liquidsoap` | Moteur de mixage, bascule auto/live       | `savonet/liquidsoap`         |
| `radio42_api`    | API REST de contrôle (Flask), pont WordPress    | Build local                  |

---

## Prérequis

- Ansible ≥ 2.12
- Accès SSH root (ou sudo) au serveur cible
- Ports disponibles : celui que vous choisissez pour Icecast (défaut 8000) et l'API (défaut 5000)
- Distributions supportées : **Debian, Ubuntu, Raspbian, Fedora, RHEL, Arch, openSUSE**

---

## Variables requises

| Variable                  | Description                          | Défaut              |
|---------------------------|--------------------------------------|---------------------|
| `stream_name`             | Nom de la radio                      | `Ma Radio 42`       |
| `icecast_source_password` | Mot de passe source Icecast          | *(obligatoire)*     |
| `icecast_admin_password`  | Mot de passe admin Icecast           | *(obligatoire)*     |
| `api_secret_key`          | Token d'auth pour le plugin WordPress| *(obligatoire)*     |
| `icecast_port`            | Port public Icecast                  | `8000`              |
| `api_port`                | Port API de contrôle                 | `5000`              |
| `live_harbor_port`        | Port Harbor pour le live micro       | `8005`              |
| `music_dir`               | Dossier musique sur l'hôte           | `/opt/radio42/music`|
| `deploy_dir`              | Dossier de déploiement               | `/opt/radio42`      |

---

## Points de montage après installation

- **Flux audio** : `http://VOTRE_IP:8000/stream`
- **Admin Icecast** : `http://VOTRE_IP:8000/admin`
- **API contrôle** : `http://VOTRE_IP:5000`
- **Musique** : `/opt/radio42/music` (uploadez vos fichiers ici)
- **Playlists** : `/opt/radio42/playlists`

---

## API — Endpoints disponibles

Tous les endpoints (sauf `/health`) nécessitent le header `Authorization: Bearer <api_secret_key>`.

| Méthode | Endpoint            | Description                        |
|---------|---------------------|------------------------------------|
| GET     | `/health`           | Healthcheck (pas d'auth)           |
| GET     | `/status`           | État MPD + auditeurs Icecast       |
| POST    | `/play`             | Lecture                            |
| POST    | `/pause`            | Pause                              |
| POST    | `/stop`             | Stop                               |
| POST    | `/next`             | Piste suivante                     |
| POST    | `/previous`         | Piste précédente                   |
| POST    | `/volume`           | Régler le volume `{"level": 75}`   |
| POST    | `/mode`             | Random/repeat/single               |
| GET     | `/queue`            | File de lecture actuelle           |
| POST    | `/queue/add`        | Ajouter `{"uri": "fichier.mp3"}`   |
| POST    | `/queue/clear`      | Vider la file                      |
| POST    | `/queue/jump/<pos>` | Sauter à la position N             |
| GET     | `/library`          | Bibliothèque (`?q=` pour chercher) |
| POST    | `/library/update`   | Rescanner la bibliothèque          |
| GET     | `/playlists`        | Lister les playlists               |
| POST    | `/playlists/<name>/load` | Charger et jouer une playlist |
| POST    | `/playlists/<name>/save` | Sauvegarder la queue           |
| DELETE  | `/playlists/<name>` | Supprimer une playlist             |
| GET     | `/stats`            | Statistiques (auditeurs, titres…)  |

---

## Mode live (micro)

Liquidsoap écoute les connexions Harbor sur le port **8005** (mappé sur l'hôte via `live_harbor_port`, défaut 8005).

Connectez un client compatible Harbor / source (ex. BUTT, Mixxx, ou outil Liquidsoap) avec :
- **Host** : IP du serveur
- **Port** : `live_harbor_port` (défaut `8005`)
- **Mot de passe** : `icecast_source_password` (même secret que la source Icecast)

La bascule est automatique : dès qu'une source live est active, elle remplace MPD dans le flux `/stream`.

---

## Licence

[Unlicense](https://unlicense.org/) — domaine public, aucune restriction.
