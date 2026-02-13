#!/bin/bash

# --- СКРИПТ ЛОКАЛЬНОЙ СБОРКИ ДЛЯ LINUX В DOCKER ---
# Этот скрипт использует официальный образ Python для запуска сборки,
# имитируя процесс из CI/CD (.github/workflows/release.yaml).
# Он не требует отдельного файла Dockerfile.

# Прерываем выполнение скрипта, если любая команда завершится с ошибкой
set -e

echo "================================================="
echo "===     Локальная сборка проекта в Docker     ==="
echo "================================================="
echo

# --- ШАГ 1: ПРОВЕРКА И УСТАНОВКА DOCKER ---
if ! command -v docker &> /dev/null
then
    echo "[INFO] Docker не найден. Начинаем установку..."
    
    sudo apt-get update
    sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io
    if ! getent group docker > /dev/null; then sudo groupadd docker; fi
    sudo usermod -aG docker $USER
    
    echo "-------------------------------------------------"
    echo "[SUCCESS] Docker успешно установлен."
    echo "[ВАЖНО] Чтобы изменения прав вступили в силу, перезапустите систему"
    echo "         или выполните команду 'newgrp docker' в этом терминале,"
    echo "         а затем запустите этот скрипт еще раз."
    echo "-------------------------------------------------"
    
    sudo systemctl start docker
    sudo systemctl enable docker
    exit 1
else
    echo "[INFO] Docker уже установлен. Пропускаем установку."
fi

if ! docker info > /dev/null 2>&1; then
    echo "[ERROR] Docker daemon не запущен. Попробуйте: sudo systemctl start docker"
    exit 1
fi

# --- ШАГ 2: ЗАПУСК СБОРКИ В КОНТЕЙНЕРЕ ---
echo
echo "[INFO] Запускаем сборку в контейнере python:3.12-bullseye..."
echo "Это может занять некоторое время при первом запуске (скачивание образа)..."
echo "-------------------------------------------------"

# Запускаем контейнер:
# --rm         - автоматически удалить контейнер после завершения работы
# -v "$(pwd)":/io - монтируем текущую папку (проект) в папку /io внутри контейнера
# -u "$(id -u):$(id -g)" - запускаем от имени текущего пользователя, чтобы
#                         созданные файлы принадлежали вам, а не root.
# python:3.12-bullseye - официальный образ, который мы используем
# bash -c "..." - команда, которая выполнится внутри контейнера.
#                  Она сначала делает build_linux.sh исполняемым, а затем запускает его.
docker run --rm \
    -v "$(pwd)":/io \
    -u "$(id -u):$(id -g)" \
    python:3.12-bullseye \
    bash -c "chmod +x /io/build_linux.sh && /io/build_linux.sh"

echo "-------------------------------------------------"
echo
echo "================================================="
echo "===       СБОРКА УСПЕШНО ЗАВЕРШЕНА!           ==="
echo "================================================="
echo "Готовый билд находится в корневой папке проекта."