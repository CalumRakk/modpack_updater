import json
import mimetypes
import shutil
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Union


def get_or_install_requests():
    try:
        import requests
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests
    return requests


def guess_type(name):
    t, _ = mimetypes.guess_type(name)
    return t or "application/octet-stream"


def read_mrpack(path: Union[str, Path]):
    path = Path(path) if isinstance(path, str) else path

    result = {"modrinth.index.json": [], "overrides": []}
    with zipfile.ZipFile(path, "r") as z:
        namelist = z.namelist()

        # --- 1. Extraer metadatos del índice ---
        if "modrinth.index.json" in namelist:
            with z.open("modrinth.index.json") as f:
                index_data = json.load(f)
                result["modrinth.index.json"] = index_data

        # --- 2. Archivos incrustados (overrides/, etc.) ---
        for name in namelist:
            if name.startswith("overrides/"):
                result["overrides"].append(
                    {
                        "path": name.removeprefix("overrides/"),
                        "content": z.read(name),
                    }
                )

    return result


def has_last_modpack_version(last_version: str):
    """Comprueba si tiene la ultima version del 'archivo .mrpack' descargada"""

    if not FOLDER_MODPACKS.exists():
        return False

    # Comprobar si el archivo .mrpack corresponde a la última versión
    for file in list(FOLDER_MODPACKS.glob("*.mrpack")):
        if last_version in file.name:
            return True
    return False


def get_last_modpack_version() -> Optional[Path]:
    """Obtiene la ultima version del 'archivo .mrpack' descargada"""
    if not FOLDER_MODPACKS.exists():
        return None

    mrpack_files = list(FOLDER_MODPACKS.glob("*.mrpack"))
    if not mrpack_files:
        return None

    latest_mrpack = max(mrpack_files, key=lambda f: f.stat().st_mtime)
    return FOLDER_MODPACKS / latest_mrpack


def download_modpack(version_url: str, output_path: Path):
    """Descarga el archivo .mrpack de la version especificada"""
    response = requests.get(version_url)

    if response.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(response.content)
        print(f"modpacks descargado en: {output_path}")
        return output_path
    else:
        print(f"Error al descargar el modpacks: {response.status_code}")
        return None


def fetch_modpack_versions(url):
    response = requests.get(url)
    if response.status_code == 200:
        versions = response.json()
        return versions
    else:
        print(f"Error al obtener versiones: {response.status_code}")
        return None


def remove_content_of_folder_mods():
    folder_mods = FOLDER_MINECRAFT / "mods"
    if folder_mods.exists():
        for mod_file in folder_mods.glob("*"):
            mod_file.unlink()


def download_mod(file, base_folder):
    """Descarga un solo mod."""
    path = base_folder / file["path"]
    url = file["downloads"][0]
    filesize = file["fileSize"]

    if path.exists() and path.stat().st_size == filesize:
        return f"✔ {file['path']} (ya actualizado)"

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        with open(path, "wb") as f:
            f.write(response.content)
        return f"⬇️ {file['path']} (descargado)"
    except Exception as e:
        return f"⚠️ Error en {file['path']}: {e}"


def main():
    modpack_versions = fetch_modpack_versions(URL_MODPACK)
    if not modpack_versions:
        return

    last_version_filename = modpack_versions[0]["files"][0]["filename"]
    last_version_url = modpack_versions[0]["files"][0]["url"]

    if not has_last_modpack_version(last_version_filename):
        print(f"Descargando la versión {last_version_filename} del modpack...")

        folder_temp = tempfile.TemporaryDirectory()
        mrpack_path = Path(folder_temp.name) / last_version_filename
        download_modpack(last_version_url, mrpack_path)

        print("Leyendo el contenido del modpack descargado...")
        data = read_mrpack(mrpack_path)

        print("\nDescargando mods en paralelo...\n")
        remove_content_of_folder_mods()

        files = data["modrinth.index.json"]["files"]  # type: ignore

        # --- Descargas concurrentes ---
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(download_mod, file, FOLDER_MINECRAFT) for file in files
            ]
            for future in as_completed(futures):
                print(future.result())

        # --- Sobrescribir overrides ---
        print("\nAplicando overrides...")
        for file in data["overrides"]:
            path = FOLDER_MINECRAFT / file["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                content = file["content"]
                if isinstance(content, str):
                    content = content.encode("utf-8", errors="ignore")
                f.write(content)
            print(f"⚙️ {file['path']} (override aplicado)")

        print("\n✅ Modpack actualizado correctamente.")
        FOLDER_MODPACKS.mkdir(parents=True, exist_ok=True)
        shutil.move(mrpack_path, FOLDER_MODPACKS / last_version_filename)


if __name__ == "__main__":
    mi_carpeta_de_minecraft = (
        r"C:\Users\Leo\AppData\Roaming\ModrinthApp\profiles\La casita del Arbol 0.0.4"
    )

    # Variables para gestionar los modpacks
    FOLDER_MINECRAFT = Path(mi_carpeta_de_minecraft)
    URL_MODPACK = "https://api.modrinth.com/v2/project/la-casita-del-arbol/version"
    FOLDER_MODPACKS = FOLDER_MINECRAFT / "modpacks"
    requests = get_or_install_requests()

    main()
