#!/bin/bash
set -ex

# 1. Обновляем пакеты и ставим ВСЕ, что нужно для PyInstaller
# Добавлен zip для финальной архивации
apt-get update
apt-get install -y gcc curl binutils patchelf zip

# 2. Устанавливаем Rust (cargo)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"

# Ограничиваем Rust одним ядром для экономии ресурсов
export CARGO_BUILD_JOBS=1

# 3. Устанавливаем зависимости Python
export PIP_ROOT_USER_ACTION=ignore
pip install --no-cache-dir --no-warn-script-location maturin
pip install --no-cache-dir --no-warn-script-location -r /io/requirements.txt

# 4. Запускаем скрипт сборки
python /io/build.py