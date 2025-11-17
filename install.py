#!/usr/bin/env python3

import os
import sys
import argparse
import shutil
import subprocess
from pathlib import Path
from typing import Optional

AUTUP_ENTRY_NAME = "update_manager klipper-better-pid"
DEFAULT_MOONRAKER_CONF = Path.home() / "printer_data/config/moonraker.conf"


IS_MAC = os.path.isdir("/System/Library")

SED_IN_PLACE_ARG = "-i ''" if IS_MAC else "-i"
FILES_TO_COPY = {
    "better_pid.py": "klippy/extras",
}


def get_script_dir():
    return os.path.dirname(os.path.realpath(__file__))


def uninstall_klipper(target_dir: str):
    for src_file, dest_dir in FILES_TO_COPY.items():
        dest_path = os.path.join(target_dir, dest_dir)
        dest_file = os.path.join(dest_path, os.path.basename(src_file))
        if os.path.islink(dest_file) or os.path.isfile(dest_file):
            print(f"Removing {dest_file}")
            os.remove(dest_file)
        else:
            print(f"File {dest_file} does not exist. Skipping.")
    return


def install_kalico(target_dir: str, uninstall: bool, copy: bool):
    if not uninstall:
        print("Installing better_pid for Kalico...")
        print("=====================================")

    python_module_path = os.path.join(target_dir, "klippy/plugins/better_pid")

    old_module_path = os.path.join(target_dir, "klippy/extras/better_pid.py")
    if os.path.islink(old_module_path) or os.path.isfile(old_module_path):
        print("Uninstalling old installation...")
        uninstall_klipper(target_dir)

    if os.path.exists(python_module_path) or os.path.islink(python_module_path):
        if not os.path.islink(python_module_path):
            print(f"{python_module_path} exists, but is not a symlink. Please remove it and try again.")
            sys.exit(1)
        os.unlink(python_module_path)

    if uninstall:
        print("Removed plugin module link.")
        sys.exit(0)

    if copy:
        shutil.copytree(get_script_dir(), python_module_path)
    else:
        os.symlink(get_script_dir(), python_module_path)

    print("Installed link to plugin module.")
    print("(There's no need to run install again after klipper-better-pid updates.)")


def install_klipper(target_dir: str, uninstall: bool, copy: bool):
    if uninstall:
        print("Uninstalling files...")
        uninstall_klipper(target_dir)
        return

    print("Installing files...")
    for src_file, dest_dir in FILES_TO_COPY.items():
        src_path = os.path.join(get_script_dir(), src_file)
        dest_path = os.path.join(target_dir, dest_dir)
        dest_file = os.path.join(dest_path, os.path.basename(src_file))

        if copy:
            print(f"Copying {src_file} to {dest_dir}/")
            shutil.copyfile(src_path, dest_file)
        else:
            link_path = os.path.relpath(os.path.realpath(src_path), dest_path)
            print(f"Linking {link_path} to {dest_dir}/")
            if os.path.islink(dest_file) or os.path.exists(dest_file):
                os.remove(dest_file)
            os.symlink(link_path, dest_file)


def get_repo_origin(repo_path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
        )
        url = result.stdout.strip()
        if url:
            return url
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    print(
        "Warning: Unable to determine git remote origin. "
        "Using placeholder URL in Moonraker config."
    )
    return "https://example.com/klipper-better-pid.git"


def prompt_conf_path(action_desc: str) -> Optional[Path]:
    conf_input = input(
        f"Path to moonraker.conf for {action_desc} [{DEFAULT_MOONRAKER_CONF}]: "
    ).strip()
    conf_path = Path(conf_input) if conf_input else DEFAULT_MOONRAKER_CONF

    if not conf_path.exists():
        print(f"Moonraker config '{conf_path}' not found.")
        return None
    return conf_path


def configure_auto_update(repo_path: str):
    response = input(
        "Enable Moonraker auto-update entry for klipper-better-pid? [y/N]: "
    ).strip().lower()
    if response not in ("y", "yes"):
        print("Auto-update not enabled.")
        return

    conf_path = prompt_conf_path("auto-update setup")
    if conf_path is None:
        print("Skipping auto-update setup.")
        return

    contents = conf_path.read_text()
    if f"[{AUTUP_ENTRY_NAME}]" in contents:
        print("Auto-update entry already exists in moonraker.conf.")
        return

    repo_url = get_repo_origin(repo_path)
    entry = (
        f"\n[{AUTUP_ENTRY_NAME}]\n"
        "type: git_repo\n"
        f"path: {repo_path}\n"
        f"origin: {repo_url}\n"
        "primary_branch: main\n"
        "install_script: install.sh\n"
        "managed_services:\n"
        "    klipper\n"
    )

    with conf_path.open("a") as f:
        f.write(entry)

    print("Added auto-update entry to moonraker.conf.")


def remove_auto_update_entry():
    conf_path = DEFAULT_MOONRAKER_CONF
    contents = []
    if conf_path.exists():
        contents = conf_path.read_text().splitlines()
    else:
        return

    new_lines = []
    in_section = False
    removed = False
    for line in contents:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped == f"[{AUTUP_ENTRY_NAME}]":
                in_section = True
                removed = True
                continue
            in_section = False
        if in_section:
            continue
        new_lines.append(line)

    if not removed:
        print("No auto-update entry found in moonraker.conf.")
        return

    text = "\n".join(new_lines)
    if text and not text.endswith("\n"):
        text += "\n"
    conf_path.write_text(text)
    print("Removed auto-update entry from moonraker.conf.")


def main():
    parser = argparse.ArgumentParser(
        description="Install or uninstall klipper-better-pid module."
    )
    parser.add_argument("-u", "--uninstall", action="store_true", help="Uninstall files")
    parser.add_argument("--copy", action="store_true", help="Copy files instead of linking")
    parser.add_argument("target_dir", nargs="?", help="Target directory")

    args = parser.parse_args()

    uninstall = args.uninstall
    copy = args.copy
    target_dir = args.target_dir

    # If no target directory provided, try defaults
    if not target_dir:
        home_dir = str(Path.home())
        if os.path.isdir(os.path.join(home_dir, "klipper")):
            target_dir = os.path.join(home_dir, "klipper")
        elif os.path.isdir(os.path.join(home_dir, "kalico")):
            target_dir = os.path.join(home_dir, "kalico")
        else:
            print("Error: No target directory provided and no default directories found.")
            parser.print_help()
            sys.exit(1)

    if not os.path.isdir(target_dir):
        print(f"Error: Target directory '{target_dir}' does not exist.")
        sys.exit(1)

    kalico = os.path.exists(os.path.join(target_dir, "klippy/extras/danger_options.py"))
    if kalico:
        install_kalico(target_dir, uninstall, copy)
    else:
        install_klipper(target_dir, uninstall, copy)

    if uninstall:
        remove_auto_update_entry()
    else:
        configure_auto_update(get_script_dir())


if __name__ == "__main__":
    main()

