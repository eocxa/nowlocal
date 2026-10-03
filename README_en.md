[Español](README.md) | [English](README_en.md) | [简体中文](README_zh.md)

# NowLocal Server & Web Player

A high-performance local audio streaming server and web player with an interface inspired by **Apple Music / Apple TV**, designed for tablets, browsers, and as a companion backend for **Minidisc (iOS)**.

> [!NOTE]
> **NowLocal** is an open-source project created strictly for educational, technical, and non-commercial purposes. Please refer to the [Legal Disclaimer](#legal-disclaimer) for details regarding usage, trademarks, and licensing.

---

## Features

- **Fluid Playback & Streaming**: Native support for `.m4a`, `.mp3`, `.flac`, `.wav`, `.aac`, `.ogg`, `.opus`, featuring byte-range requests (`HTTP 206 Partial Content`) for instantaneous seeking and scrubbing.
- **Synchronized Lyrics (Word-by-Word & TTML)**:
  - Native parsing of `.ttml` files (Apple Music Timed Text with syllable-level synchronization and v1/v2 vocal separation).
  - Standard synchronized `.lrc` files and embedded metadata lyrics (ID3 / MP4).
  - Smooth and interactive web rendering powered by [**Apple Music-like Lyrics (AMLL)**](https://github.com/amll-dev/applemusic-like-lyrics).
  - Automatic fallback to [**LRCLIB**](https://lrclib.net) when a track lacks local lyrics.
- **Dynamic Artwork & Motion Canvas**: High-resolution embedded cover extraction and support for animated cover videos (`.mp4` square and tall aspect ratios).
- **Intelligent LRU Cache**: Configurable audio cache size with automated Least Recently Used (LRU) eviction to keep storage strictly managed.
- **Minidisc (iOS) Integration**: Dedicated REST endpoints (`/api/enrichment`, `/api/lyrics/{id}`, `/api/artwork/...`) delivering enriched metadata, TTML lyrics, and motion covers to iPhone and iPad.
- **Responsive Web Interface**: Web app rendering at 60/120 FPS with dynamic ambient background colors extracted from album artwork, along with full touch and keyboard controls.

---

## Quick Start

### Option 1: With Docker Compose (Recommended)

1. Clone this repository:
   ```bash
   git clone https://github.com/eocxa/nowlocal.git
   cd nowlocal
   ```

2. Edit `docker-compose.yml` to bind your local music directory:
   ```yaml
   volumes:
     - /path/to/your/music:/music:ro
     - cache_audio:/app/.cache_audio
     - cache_covers:/app/.cache_covers
     - ./config.json:/app/config.json
   ```

3. Start the container:
   ```bash
   docker compose up -d
   ```

4. Open in your browser:
   - **Desktop / Tablet Interface**: `http://localhost:8000`
   - **Mobile Interface**: `http://localhost:8000/movil`

---

### Option 2: Local Execution with Python

1. **Requirements**:
   - Python 3.10 or higher
   - `ffmpeg` installed and available in the system `PATH` (required for audio transcoding and advanced format support).

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the server**:
   - On **Windows**: Double-click `iniciar_completo.bat` or run:
     ```cmd
     python servidor_completo.py
     ```
   - On **Linux / macOS**:
     ```bash
     python3 servidor_completo.py
     ```

---

## Configuration

The server can be configured using environment variables or via `config.json`:

| Environment Variable | Description | Default Value |
|----------------------|-------------|---------------|
| `PORT`               | HTTP server port | `8000` |
| `MUSIC_DIR`          | Absolute path to music directory | User `~/Music` folder |

You can also update the music directory dynamically from the web interface or via a POST request to `/api/config`:
```bash
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"music_dir": "/your/music/folder"}'
```

---

## Connecting to Minidisc (iOS)

To connect your Minidisc iOS client to this NowLocal server:

1. Open **Minidisc** on your iOS device.
2. Go to **Settings** > **Integrations**.
3. Select the **NowLocal** or **Animated Artwork** tab.
4. Enter your server IP or domain and port (for example: `http://192.168.1.100:8000`).
5. All set! Minidisc will automatically fetch advanced TTML lyrics, audio badges, and animated motion artwork directly from your local library.

---

## Legal Disclaimer

> [!WARNING]
> **Important Notice on Usage, Responsibility, and Copyright:**
>
> 1. **Educational Purpose & Visual Imitation**: This project (**NowLocal**) is an experimental, personal, and open-source project created solely for technical research and learning regarding web technologies (HTML5 Canvas, WebSockets, TTML subtitle rendering, and HTTP audio streaming). **It is purely an interface recreation and imitation** inspired by modern media players.
>
> 2. **Non-Commercial**: This software is 100% free and open source. **It is not sold, monetized, commercially distributed, or charged for** under any circumstances. No subscriptions, fees, or access charges exist.
>
> 3. **No Copyrighted Content Included**: This repository **DOES NOT contain, distribute, or host any music files, songs, albums, commercial artwork, or copyrighted material**. The software is solely a blank media playback server engine that operates privately on the user's own local library.
>
> 4. **User Responsibility**: The use of this software is at the **sole and exclusive responsibility of the end user**. Each user is entirely responsible for possessing legitimate licenses, authorized backups, or appropriate rights for any audio tracks or files they choose to store, index, or stream over their network. The author and contributors disclaim any liability for improper or unauthorized use.
>
> 5. **Trademark Notice**: *Apple*, *Apple Music*, *Apple TV*, *iOS*, *macOS*, *ALAC*, *Dolby Atmos*, and all other trademarks, product names, or logos referenced belong to their respective owners (Apple Inc. and/or other entities). They are cited solely for descriptive, informative, and technical interoperability purposes (*Fair Use*). This project is not affiliated with, endorsed by, sponsored by, or connected to Apple Inc. or any commercial music streaming service.

---

## Acknowledgments & Credits

- [**Apple Music-like Lyrics (AMLL)**](https://github.com/amll-dev/applemusic-like-lyrics) by **amll-dev**: Superb library and engine utilized for web-based synchronized lyrics rendering and Apple Music-style typography animations.

---

## License

This project is licensed under the MIT License.
