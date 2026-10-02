# NowLocal Server & Web Player 🎵

Un servidor de streaming de audio local de alto rendimiento y reproductor web con fidelidad **Apple Music / Apple TV**, diseñado para tablets, navegadores y como backend complementario para **Minidisc (iOS)**.

---

## ✨ Características Principales

- **Reproducción & Streaming Fluido**: Soporte nativo para `.m4a`, `.mp3`, `.flac`, `.wav`, `.aac`, `.ogg`, `.opus`, con peticiones por rango (`HTTP 206 Partial Content`) para scrubbing y seek instantáneo.
- **Letras Sincronizadas (Word-by-Word & TTML)**:
  - Lectura nativa de archivos `.ttml` (Apple Music Timed Text con sincronización sílaba por sílaba y división de voces v1/v2).
  - Letras estándar `.lrc`.
  - Letras embebidas en metadatos ID3 / MP4.
  - Fallback automático a **LRCLIB** cuando la pista no cuenta con letra local.
- **Portadas Dinámicas & Motion Artwork**: Extracción automática de carátulas embebidas en alta resolución y soporte para portadas animadas (`.mp4` square y tall).
- **Caché Inteligente LRU**: Límite de caché de audio configurable con política LRU (Least Recently Used) para mantener el almacenamiento siempre bajo control.
- **Integración con Minidisc (iOS)**: Endpoints REST optimizados (`/api/enrichment`, `/api/lyrics/{id}`, `/api/artwork/...`) para enriquecer la experiencia en iPhone y iPad.
- **Interfaz Web Reactiva**: Web app responsive a 60/120 FPS con fondos ambientales dinámicos extraídos de la portada y control táctil/teclado.

---

## 🚀 Despliegue Rápido

### Opción 1: Con Docker Compose (Recomendado)

1. Clona este repositorio:
   ```bash
   git clone https://github.com/eocxa/nowlocal.git
   cd nowlocal
   ```

2. Edita `docker-compose.yml` para vincular tu carpeta de música:
   ```yaml
   volumes:
     - /ruta/a/tu/musica:/music:ro
     - cache_audio:/app/.cache_audio
     - cache_covers:/app/.cache_covers
     - ./config.json:/app/config.json
   ```

3. Inicia el contenedor:
   ```bash
   docker compose up -d
   ```

4. Abre en tu navegador:
   - **Interfaz Escritorio/Tablet**: `http://localhost:8000`
   - **Interfaz Móvil**: `http://localhost:8000/movil`

---

### Opción 2: Ejecución Local con Python

1. **Requisitos**:
   - Python 3.10 o superior
   - `ffmpeg` instalado y disponible en el `PATH` del sistema (requerido para transcodificación de audio y lectura de formatos avanzados).

2. **Instalación de dependencias**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Iniciar el servidor**:
   - En **Windows**: Haz doble clic en `iniciar_completo.bat` o ejecuta:
     ```cmd
     python servidor_completo.py
     ```
   - En **Linux / macOS**:
     ```bash
     python3 servidor_completo.py
     ```

---

## ⚙️ Configuración

El servidor se puede configurar mediante variables de entorno o a través de `config.json`:

| Variable de Entorno | Descripción | Valor por Defecto |
|---------------------|-------------|-------------------|
| `PORT`              | Puerto HTTP del servidor | `8000` |
| `MUSIC_DIR`         | Ruta absoluta a la carpeta de música | Carpeta `~/Music` del usuario |

También puedes cambiar la carpeta de música en cualquier momento desde la interfaz web o mediante una petición POST a `/api/config`:
```bash
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"music_dir": "/mi/musica"}'
```

---

## 📱 Conexión con Minidisc (iOS)

Para conectar tu cliente de Minidisc a este servidor NowLocal:

1. Abre **Minidisc** en tu dispositivo iOS.
2. Ve a **Configuración** (`Settings`) > **Integraciones**.
3. Selecciona la pestaña **NowLocal** o **Animated Artwork**.
4. Ingresa la dirección IP o dominio de tu servidor y puerto (por ejemplo: `http://192.168.1.100:8000`).
5. ¡Listo! Minidisc cargará automáticamente las letras TTML avanzadas, indicadores de audio y portadas animadas desde tu biblioteca local.

---

## 📄 Licencia

Este proyecto está bajo la Licencia MIT.
