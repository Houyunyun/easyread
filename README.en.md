# EasyRead

Read papers at your own pace. Drop in a PDF and start reading as soon as the first translated passage appears. Compare a passage with the original page, highlight it, leave a note or ask a question in the margin. You can also read the English original.

[Download](https://github.com/Edwardxlai/easyread/releases/latest) · [Try the demo](https://edwardxlai.github.io/easyread/demo/) · [Project site](https://edwardxlai.github.io/easyread/en/) · [简体中文](README.md)

![Translated text alongside the original PDF](docs/images/en/hero.png)

## Install

Choose the Windows installer (`.exe`), Apple silicon Mac disk image (`.dmg`) or Linux AppImage from the download page. See the [installation guide](docs/guide.en.md#install) for first-launch instructions.

<a id="run-from-source"></a>

To run from source with Python 3.10+, double-click `start.cmd` on Windows or run `./start.sh` on macOS or Linux.

## Docker browser version

```bash
git clone https://github.com/Jasaxion/easyread.git
cd easyread
docker compose up -d --build
```

Open <http://127.0.0.1:8765> on the server. The default published port is loopback-only, and data persists in a Docker volume. Use an SSH tunnel or an authenticating reverse proxy for remote access. See the [Docker deployment guide](docs/docker.en.md) for LAN access, models and backups. There is no built-in login; do not expose the app directly to the public Internet.

## Read your first paper

1. Drop in a PDF, enter an arXiv ID, or paste a blog URL. Pick a translation language or read the original.
2. For translation or questions, select a supported CLI you are signed in to, or configure a model API in Settings. Your library lives on your computer. The selected model receives the material needed for your request.
3. Open the PDF and your notes side by side. To find something you read earlier, choose **Ask the library** and follow a citation back to its passage.

Research planning, reading paths, editable AI mind maps, handwriting and stickers, deep/cross-paper analysis, split tabs and Obsidian export are integrated with the existing reader. See the [research guide](docs/research.en.md) for entry points, model requirements and data behavior.

[User guide](docs/guide.en.md) · [Research features](docs/research.en.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Contributors](docs/guide.en.md#contributors) · [License and demo paper credit](docs/guide.en.md#license)
