[Español](README.md) | [English](README_en.md) | [简体中文](README_zh.md)

# NowLocal Server & Web Player

Un servidor de streaming de audio local de alto rendimiento y reproductor web con interfaz inspirada en **Apple Music / Apple TV**, diseñado para tablets, navegadores y como backend complementario para **Minidisc (iOS)**.

> [!NOTE]
> **NowLocal** es un desarrollo de código abierto puramente educativo y no comercial. Consulta el [Descargo de Responsabilidad](#descargo-de-responsabilidad--legal-disclaimer) para más detalles sobre uso, marcas y licencias.

---

## Características Principales

- **Reproducción & Streaming Fluido**: Soporte nativo para `.m4a`, `.mp3`, `.flac`, `.wav`, `.aac`, `.ogg`, `.opus`, con peticiones por rango (`HTTP 206 Partial Content`) para scrubbing y seek instantáneo.
- **Letras Sincronizadas (Word-by-Word & TTML)**:
  - Lectura nativa de archivos `.ttml` (Apple Music Timed Text con sincronización sílaba por sílaba y división de voces v1/v2).
  - Letras estándar `.lrc` y embebidas en metadatos ID3 / MP4.
  - Renderizado web interactivo y fluido potenciado por [**Apple Music-like Lyrics (AMLL)**](https://github.com/amll-dev/applemusic-like-lyrics).
  - Fallback automático a **LRCLIB** cuando la pista no cuenta con letra local.
- **Portadas Dinámicas & Motion Artwork**: Extracción automática de carátulas embebidas en alta resolución y soporte para portadas animadas (`.mp4` square y tall).
- **Caché Inteligente LRU**: Límite de caché de audio configurable con política LRU (Least Recently Used) para mantener el almacenamiento siempre bajo control.
- **Integración con Minidisc (iOS)**: Endpoints REST optimizados (`/api/enrichment`, `/api/lyrics/{id}`, `/api/artwork/...`) para enriquecer la experiencia en iPhone y iPad.
- **Interfaz Web Reactiva**: Web app responsive a 60/120 FPS con fondos ambientales dinámicos extraídos de la portada y control táctil/teclado.

---

## Despliegue Rápido

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
   - **Interfaz Escritorio/Tablet**: `http://localhost:7430`
   - **Interfaz Móvil**: `http://localhost:7430/movil`

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

## Configuración

El servidor se puede configurar mediante variables de entorno o a través de `config.json`:

| Variable de Entorno | Descripción | Valor por Defecto |
|---------------------|-------------|-------------------|
| `PORT`              | Puerto HTTP del servidor | `7430` |
| `MUSIC_DIR`         | Ruta absoluta a la carpeta de música | Carpeta `~/Music` del usuario |

También puedes cambiar la carpeta de música en cualquier momento desde la interfaz web o mediante una petición POST a `/api/config`:
```bash
curl -X POST http://localhost:7430/api/config \
  -H "Content-Type: application/json" \
  -d '{"music_dir": "/mi/musica"}'
```

---

## Conexión con Minidisc (iOS)

Para conectar tu cliente de Minidisc a este servidor NowLocal:

1. Abre **Minidisc** en tu dispositivo iOS.
2. Ve a **Configuración** (`Settings`) > **Integraciones**.
3. Selecciona la pestaña **NowLocal** o **Animated Artwork**.
4. Ingresa la dirección IP o dominio de tu servidor y puerto (por ejemplo: `http://192.168.1.100:7430`).
5. ¡Listo! Minidisc cargará automáticamente las letras TTML avanzadas, indicadores de audio y portadas animadas desde tu biblioteca local.

---

## Descargo de Responsabilidad / Legal Disclaimer

> [!WARNING]
> **Aviso Importante sobre Uso, Responsabilidad y Derechos de Autor:**
>
> 1. **Propósito Educativo e Imitación Visual**: Este proyecto (**NowLocal**) es un desarrollo experimental, personal y de código abierto creado con fines de investigación técnica y aprendizaje sobre tecnologías web (HTML5 Canvas, WebSockets, renderizado de subtítulos TTML y streaming HTTP de audio). **Es únicamente una recreación e imitación de interfaz gráfica** inspirada en los reproductores modernos de música.
>
> 2. **Sin Fines de Lucro ni Comercialización**: Este software es 100% gratuito y de código abierto. **No se comercializa, vende, distribuye con costo ni monetiza** bajo ninguna modalidad. No se cobran suscripciones, accesos ni donaciones por su utilización.
>
> 3. **Ausencia de Contenido Protegido (Sin Copyright)**: Este repositorio **NO contiene, distribuye ni aloja archivos de música, canciones, álbumes, carátulas comerciales ni ningún material multimedia protegido por derechos de autor**. El software es únicamente un motor de reproducción en blanco que trabaja de forma local y privada con la biblioteca personal que el propio usuario configure en su dispositivo o servidor.
>
> 4. **Responsabilidad Exclusiva del Usuario**: El uso que se le dé a este software queda bajo la **exclusiva y total responsabilidad del usuario final**. Cada persona es responsable de contar con las licencias legítimas, copias de respaldo autorizadas o derechos correspondientes sobre cualquier pista de audio o archivo que decida reproducir o transmitir en su red. El autor y los contribuidores se deslindan de cualquier uso indebido o no autorizado.
>
> 5. **Aviso de Marcas Registradas**: *Apple*, *Apple Music*, *Apple TV*, *iOS*, *macOS*, *ALAC*, *Dolby Atmos* y todas las marcas, nombres de productos o logotipos mencionados pertenecen a sus respectivos titulares (Apple Inc. y/u otras entidades). Se mencionan únicamente con carácter informativo y descriptivo para indicar compatibilidad de formatos e interoperabilidad técnica (*Fair Use / Uso Legítimo*). Este software no tiene relación, patrocinio, afiliación ni respaldo oficial por parte de Apple Inc. ni de plataformas comerciales.

---

## Agradecimientos y Créditos

- [**Minidisc**](https://github.com/Loriage/Minidisc) de **Loriage**: El cliente de música original para iOS que inspiró la creación de este backend y reproductor de enriquecimiento local.
- [**Apple Music-like Lyrics (AMLL)**](https://github.com/amll-dev/applemusic-like-lyrics) de **amll-dev**: Biblioteca de referencia y motor utilizado para el renderizado web de letras sincronizadas y efectos visuales tipográficos estilo Apple Music.

---

## Licencia

Este proyecto está bajo la [Licencia MIT](LICENSE).
