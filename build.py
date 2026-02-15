import os
import sys
import shutil
import subprocess
import glob
from setuptools import setup, Extension
from Cython.Build import cythonize
import platform
from typing import Set, Iterable
import marshal
import base64
import Cython.Compiler.Options

# Запрещаем докстринги компилятору Cython
Cython.Compiler.Options.docstrings = False

# --- CONFIG ---
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR = os.path.join(PROJECT_DIR, "media")
SANDBOX_DIR = os.path.join(PROJECT_DIR, "_build_zone")
RUST_MODULE_DIR = os.path.join(PROJECT_DIR, "rust_module")
MAIN_FILE = "main.py"
BUILD_NAME = "EVM_TERMINAL"


def ignore_db_files(directory: str, files: Iterable[str]) -> Set[str]:
    ignored = set()
    for file in files:
        if file.endswith(('.db', '.sqlite', '.log', '.md', '.gitignore', '.ini')):
            ignored.add(file)
        elif directory.endswith('data') and file == '.keep':
            continue
        elif directory == PROJECT_DIR and file in ("test.py"):
            ignored.add(file)
    return ignored


def prepare_sandbox():
    os.chdir(PROJECT_DIR)
    if os.path.exists(SANDBOX_DIR):
        try: shutil.rmtree(SANDBOX_DIR)
        except Exception as e: print(f"[WARN] Could not clean sandbox: {e}")

    print(f"--- Copying project to sandbox: {SANDBOX_DIR} ---")
    
    def custom_ignore_func(directory, files):
        base_ignore = shutil.ignore_patterns(
            "env", "venv", ".venv", ".git", ".idea", "__pycache__", ".txt", "tests",
            "build", "dist", "logs", "_build_zone", "contract", "*.pyc", "*.c", "*.md",
            "build_linux.sh", "local_build.sh", "rust_module", "tests", ".gitignore",
            "rust_module.egg-info", "test.py", "*.db", "*.sqlite", "*.log",
        )
        ignored = base_ignore(directory, files)
        if directory.endswith('data'):
            db_ignored = ignore_db_files(directory, files)
            ignored.update(db_ignored)
        return ignored

    shutil.copytree(PROJECT_DIR, SANDBOX_DIR, ignore=custom_ignore_func)
    
    data_dst = os.path.join(SANDBOX_DIR, "data")
    if not os.path.exists(data_dst): 
        os.makedirs(data_dst)


def compile_rust_module():
    print("--- Building Rust Core (dexbot_core) ---")
    if not os.path.exists(RUST_MODULE_DIR):
        print("[WARN] Rust module directory not found.")
        return
    cmd = [sys.executable, "-m", "maturin", "build", "--release", "--strip"]
    target_arch = os.environ.get('TARGET_ARCH')
    if sys.platform == 'darwin' and target_arch:
        if target_arch == 'x86_64': cmd.extend(["--target", "x86_64-apple-darwin"])
        elif target_arch == 'arm64': cmd.extend(["--target", "aarch64-apple-darwin"])
    
    print(f"Executing Maturin: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=RUST_MODULE_DIR)
    
    wheels_dir = os.path.join(RUST_MODULE_DIR, "target", "wheels")
    whl_files = glob.glob(os.path.join(wheels_dir, "*.whl"))
    if not whl_files: raise Exception("Rust build failed")
    latest_whl = max(whl_files, key=os.path.getctime)
    subprocess.check_call([sys.executable, "-m", "pip", "install", latest_whl, "--force-reinstall"])


def get_extensions_in_sandbox():
    extensions = []
    c_flags = []
    if os.name == 'nt': c_flags = ["/O2", "/GL"]
    else:
        c_flags = ["-O3"]
        if sys.platform != 'darwin': c_flags.append("-flto")
    for root, _, files in os.walk("."):
        for file in files:
            if file.endswith(".py") and file not in [MAIN_FILE, "build.py"]:
                full_path = os.path.join(root, file)
                if "data" in full_path.split(os.sep): continue
                module_name = os.path.splitext(os.path.relpath(full_path, "."))[0].replace(os.sep, ".")
                extensions.append(Extension(name=module_name, sources=[full_path], extra_compile_args=c_flags))
    return extensions


def compile_cython():
    # NOTE: Легаси функция для защиты от реверс-инжиниринга (как один из дополнительных слоев). 
    # Оставлена, так как немного экономит место на жестком диске
    print("--- Compiling Cython modules (.so files) ---")
    os.chdir(SANDBOX_DIR)
    try:
        setup(
            ext_modules=cythonize(
                get_extensions_in_sandbox(),
                compiler_directives={'language_level': "3", 'emit_code_comments': False},
            ),
            script_args=["build_ext", "--inplace"]
        )
    except SystemExit: raise Exception("Cython compilation failed!")


def run_pyinstaller():
    print("--- Running PyInstaller (ONEDIR MODE) ---")
    os.chdir(SANDBOX_DIR)
    sep = ';' if os.name == 'nt' else ':'

    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--console",
        "--name", BUILD_NAME, "--clean",
        f"--add-data", f"tui/app.css{sep}tui",
        f"--add-data", f"data{sep}data", 
        f"--add-data", f"networks{sep}networks",
        "--hidden-import", "dexbot_core"
    ]
    
    # ИКОНКА
    icon_ico = os.path.join(MEDIA_DIR, "icon.ico")
    icon_icns = os.path.join(MEDIA_DIR, "icon.icns")
    if sys.platform == 'win32' and os.path.exists(icon_ico):
        cmd.extend(["--icon", icon_ico])
    elif sys.platform == 'darwin' and os.path.exists(icon_icns):
        cmd.extend(["--icon", icon_icns])

    # Сбор всех внешних пакетов из requirements.txt
    print("--- Collecting third-party packages ---")
    req_file = os.path.join(PROJECT_DIR, 'requirements.txt')
    try:
        with open(req_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                package_name = line.split('==')[0].split('>=')[0].split('<')[0].strip()
                if package_name:
                    cmd.extend(["--collect-all", package_name])
    except: pass

    # ПРИНУДИТЕЛЬНЫЙ СБОР ВСЕХ МОДУЛЕЙ ПРОЕКТА
    print("--- Collecting all project modules ---")
    project_roots = ("bot", "tui", "utils", "networks")
    for root, _, files in os.walk("."):
        rel_path = os.path.relpath(root, ".")
        if not rel_path.startswith(project_roots): continue
        for file in files:
            if file.endswith(".py"):
                module_path = os.path.join(rel_path, os.path.splitext(file)[0])
                module_name = module_path.replace(os.sep, '.')
                cmd.extend(["--hidden-import", module_name])

    cmd.append(MAIN_FILE)
    print(f"Executing PyInstaller...")
    subprocess.check_call(cmd)


def move_binary_back():
    print("--- Moving artifact back ---")
    dist_dir = os.path.join(SANDBOX_DIR, "dist")
    source_folder = os.path.join(dist_dir, BUILD_NAME)
    
    system_name = sys.platform
    machine_arch = (os.environ.get('TARGET_ARCH') or platform.machine()).lower()
    if machine_arch == "amd64": machine_arch = "x86_64"
    
    if system_name == 'win32': out_name = f"{BUILD_NAME}_Windows_{machine_arch}"
    elif system_name == 'darwin': out_name = f"{BUILD_NAME}_MacOS_{machine_arch}"
    else: out_name = f"{BUILD_NAME}_Linux_{machine_arch}"
    
    dst = os.path.join(PROJECT_DIR, out_name)
    
    if os.path.exists(source_folder):
        if os.path.exists(dst):
            if os.path.isdir(dst): shutil.rmtree(dst)
            else: os.remove(dst)
        
        # 1. Перемещаем основную папку сборки
        shutil.move(source_folder, dst)
        
        # 2. ПРИНУДИТЕЛЬНО КОПИРУЕМ NETWORKS В КОРЕНЬ БИЛДА
        # Rust ищет ./networks, поэтому она должна лежать рядом с бинарником
        networks_src = os.path.join(PROJECT_DIR, "networks")
        networks_dst = os.path.join(dst, "networks")
        
        if os.path.exists(networks_src):
            if os.path.exists(networks_dst):
                shutil.rmtree(networks_dst)
            shutil.copytree(networks_src, networks_dst)
            print(f"Manually copied 'networks' folder to: {networks_dst}")
        else:
            print("[WARN] Original 'networks' folder not found! Bot will silent exit.")

        print(f"SUCCESS! Binary saved to: {dst}")
    else:
        raise Exception("Artifact generation failed")


def cleanup_sandbox():
    print("--- Cleanup Sandbox ---")
    os.chdir(PROJECT_DIR)
    if os.path.exists(SANDBOX_DIR):
        try: shutil.rmtree(SANDBOX_DIR)
        except Exception: pass


if __name__ == "__main__":
    try:
        compile_rust_module()
        prepare_sandbox()
        compile_cython()
        run_pyinstaller()
        move_binary_back()
    except Exception as e:
        print(f"\nCRITICAL BUILD ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cleanup_sandbox()