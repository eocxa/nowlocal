[Español](README.md) | [English](README_en.md) | [简体中文](README_zh.md)

# NowLocal 本地音频流媒体服务与 Web 播放器

高性能本地音频流媒体服务器与 Web 播放器，拥有受 **Apple Music / Apple TV** 启发的交互界面，专为平板、桌面浏览器设计，并作为 **Minidisc (iOS)** 的本地增强伴侣后端。

> [!NOTE]
> **NowLocal** 是一个纯用于技术研究与非商业用途的开源项目。有关使用条款、商标和版权信息，请参阅[免责声明](#免责声明--legal-disclaimer)。

---

## 主要特性

- **流畅播放与流媒体传输**: 原生支持 `.m4a`、`.mp3`、`.flac`、`.wav`、`.aac`、`.ogg`、`.opus` 等格式，支持字节范围请求 (`HTTP 206 Partial Content`)，实现零延迟拖动定位与快进播放。
- **逐字同步歌词 (Word-by-Word & TTML)**:
  - 原生解析 `.ttml` 格式歌词（Apple Music Timed Text，支持音节级平滑渐变与 v1/v2 多歌手声道空间分离布局）。
  - 支持标准 `.lrc` 歌词与内嵌于 ID3 / MP4 标签中的元数据歌词。
  - 采用 [**Apple Music-like Lyrics (AMLL)**](https://github.com/amll-dev/applemusic-like-lyrics) 渲染引擎，实现极佳的 Web 歌词动效与文字排版。
  - 当本地无歌词文件时，自动回退至 [**LRCLIB**](https://lrclib.net) 获取云端同步歌词。
- **动态封面与动效视频 (Motion Artwork)**: 自动提取内嵌高分辨率专辑封面，并支持方形与竖版动效视频封面 (`.mp4`) 无缝循环播放。
- **智能 LRU 缓存管理**: 支持自定义音频缓存容量上限，内置 LRU (最近最少使用) 自动淘汰算法，确保存储空间稳定受控。
- **Minidisc (iOS) 专属生态联动**: 提供 REST API 接口 (`/api/enrichment`、`/api/lyrics/{id}`、`/api/artwork/...`)，为 Minidisc 提供丰富的本地歌词、音频标签与动效封面。
- **响应式现代化 Web 界面**: 支持 60/120 FPS 高帧率渲染，基于封面自适应提取动态环境光渐变背景，全面支持触摸与键盘快捷操作。

---

## 快速开始

### 方式 1: 使用 Docker Compose 部署 (推荐)

1. 克隆本仓库:
   ```bash
   git clone https://github.com/eocxa/nowlocal.git
   cd nowlocal
   ```

2. 编辑 `docker-compose.yml` 挂载您的本地音乐目录:
   ```yaml
   volumes:
     - /你的/本地/音乐目录:/music:ro
     - cache_audio:/app/.cache_audio
     - cache_covers:/app/.cache_covers
     - ./config.json:/app/config.json
   ```

3. 启动容器:
   ```bash
   docker compose up -d
   ```

4. 在浏览器中访问:
   - **桌面 / 平板界面**: `http://localhost:8000`
   - **移动端界面**: `http://localhost:8000/movil`

---

### 方式 2: 使用 Python 本地运行

1. **运行要求**:
   - Python 3.10 或更高版本
   - 系统 `PATH` 中需安装并配置 `ffmpeg`（用于音频转码与高级格式解析）。

2. **安装依赖**:
   ```bash
   pip install -r requirements.txt
   ```

3. **启动服务器**:
   - **Windows**: 双击运行 `iniciar_completo.bat` 或在终端中执行:
     ```cmd
     python servidor_completo.py
     ```
   - **Linux / macOS**:
     ```bash
     python3 servidor_completo.py
     ```

---

## 配置说明

服务器支持通过环境变量或 `config.json` 文件进行配置:

| 环境变量 | 配置描述 | 默认值 |
|----------|----------|--------|
| `PORT`   | HTTP 服务监听端口 | `8000` |
| `MUSIC_DIR` | 音乐媒体目录绝对路径 | 当前用户的 `~/Music` 文件夹 |

您也可以随时在 Web 界面中修改音乐目录，或通过向 `/api/config` 发送 POST 请求更新:
```bash
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"music_dir": "/你的/音乐目录"}'
```

---

## 连接至 Minidisc (iOS)

如需将 Minidisc 客户端连接到本 NowLocal 服务:

1. 在 iOS 设备上打开 **Minidisc**。
2. 进入 **设置** (`Settings`) > **扩展集成** (`Integrations`)。
3. 选择 **NowLocal** 或 **Animated Artwork** 选项卡。
4. 输入您的服务器 IP 地址或域名及端口（例如: `http://192.168.1.100:8000`）。
5. 配置完成！Minidisc 将自动从您的私有服务器加载丰富的 TTML 歌词、音质标识与动态封面视频。

---

## 免责声明 / Legal Disclaimer

> [!WARNING]
> **关于软件使用、责任限制与知识产权的重要声明:**
>
> 1. **技术研究与视觉模仿目的**: 本项目 (**NowLocal**) 为个人开发者建立的开源实验项目，仅供 Web 技术研究、网络流媒体协议交互与字幕排版演进之用。**界面设计仅为向现代主流流媒体播放器致敬的技术模仿与重构**。
>
> 2. **非商业性质**: 本软件完全免费、开源。**绝不存在任何形式的商业销售、付费分发、广告获利、付费会员或捐赠绑定行为**。
>
> 3. **无内置版权内容**: 本项目代码仓库**严禁且绝不包含、不托管、不分发任何音乐音频文件、唱片封面图像或其他受版权保护的音像资产**。本软件仅作为中立的空白播放引擎运行，完全依赖用户在本地搭建与合法配置的媒体库。
>
> 4. **使用者独立法律责任**: 本软件的使用以及流媒体传输行为由**最终用户独立承担全部责任**。每位使用者必须确保对其在服务中引入、索引与播放的全部音频及图像文件持有合法授权、正版购买凭证或符合当地法律规定的合理备份权利。项目作者与贡献者不对用户的任何侵权或不当使用行为承担任何责任。
>
> 5. **商标与品牌归属**: *Apple*, *Apple Music*, *Apple TV*, *iOS*, *macOS*, *ALAC*, *Dolby Atmos* 以及本文档中提及的其他任何品牌与产品名称，均为 Apple Inc. 或其相应权利人持有的注册商标。文档与代码中的提及仅出于技术格式兼容性与互操作性说明的合理使用目的 (*Fair Use*)。本项目与 Apple Inc. 或任何商业流媒体服务平台无任何隶属、合作、赞助或官方背书关系。

---

## 致谢与鸣谢

- [**Apple Music-like Lyrics (AMLL)**](https://github.com/amll-dev/applemusic-like-lyrics) 由 **amll-dev** 开发: 本项目 Web 界面中采用的卓越歌词渲染与排版动效引擎。

---

## 许可证

本项目基于 MIT License 协议开源。
