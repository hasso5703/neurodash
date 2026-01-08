# Contributing to NeuroDash

First off, thank you for considering contributing to NeuroDash!
## ⚡ Quick Start

This project uses `uv` for dependency management.

1. **Fork the repository**
2. **Clone your fork:**
   ```bash
   git clone https://github.com/hasso5703/neurodash.git
   cd neurodash
   ```
3. **Sync dependencies:**
   ```bash
   uv sync
   ```
4. **Create a branch:**
   ```bash
   git checkout -b feat/my-new-feature
   ```

## 🛠 Development Guidelines

* **Single File Philosophy:** We aim to keep the core logic in `main.py` for easy portability. Avoid creating multiple modules unless absolutely necessary.
* **Performance First:** This is a monitoring tool. It must consume negligible resources. Avoid heavy libraries (pandas, numpy) if standard lists/dicts suffice.
* **Linting:** We use `ruff` for linting.
    ```bash
    uv run ruff check .
    ```

## 📮 Pull Requests

* Describe your changes in detail.
* Link to any relevant issues.
* Ensure your code runs in both GPU and CPU-only modes (test on a non-NVIDIA machine if possible).

## 🐛 Reporting Bugs

Please include:
* Your OS (Ubuntu 24.04, Windows 11, etc.)
* NVIDIA Driver Version (`nvidia-smi`)
* Python Version
* Logs from the console or systemd service.

Thank you for helping build the best AI Workstation Monitor!