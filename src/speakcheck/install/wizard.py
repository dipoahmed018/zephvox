"""`speakcheck setup`: detect the machine, pick a profile, install and download what it needs.

Safe to run again at any time: to change profile, after an update, or to repair an install.
Every question has a default, and `--yes` (or no terminal) accepts them all.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from ..engine import hardware, profiles
from ..engine.config import (
    Config,
    choose_profile,
    default_config_path,
    load_config,
    load_user_settings,
    project_root,
    save_user_settings,
    write_profile,
)
from ..engine.errors import SpeakcheckError
from ..providers.base import Download
from . import ollama
from .download import cache_path, plan_downloads
from .state import ROLES, InstallState, Runner, SetupError, extras_for, sync

SELFTEST_CLIP = Path(__file__).resolve().parent.parent / "data" / "selftest.wav"
STEPS = 7
ROLE_CHOICES = [
    ("full", "On this computer: record and analyze here (downloads the models)"),
    ("client", "Use a speakcheck server: record here, analyze there (small install, needs an invite)"),
    ("server", "Server only: analyze for other devices (no app menu entry or microphone)"),
]


class Console:
    """Questions with defaults; non-interactive runs take the defaults."""

    def __init__(self, interactive: bool, ask: Callable[[str], str] = input, out: Callable[[str], None] | None = None):
        self.interactive, self._ask = interactive, ask
        # Flushed: subprocesses (uv, downloads) write to the same terminal in between.
        self.say = out or (lambda text="": print(text, flush=True))
        self._step = 0
        self.total = STEPS

    def step(self, title: str) -> None:
        self._step += 1
        self.say(f"\n[{self._step}/{self.total}] {title}")

    def text(self, question: str, default: str = "") -> str:
        if not self.interactive:
            return default
        answer = self._ask(f"{question}{f' [{default}]' if default else ''} ").strip()
        return answer or default

    def confirm(self, question: str, default: bool = True) -> bool:
        if not self.interactive:
            return default
        hint = "Y/n" if default else "y/N"
        while True:
            answer = self._ask(f"{question} [{hint}] ").strip().lower()
            if not answer:
                return default
            if answer in ("y", "yes", "n", "no"):
                return answer.startswith("y")

    def choose(self, question: str, options: list[tuple[str, str]], default: str) -> str:
        """`options` are (value, label) pairs; pick by number or value."""
        for i, (value, label) in enumerate(options, 1):
            self.say(f"  {i}. {label}{'   ← default' if value == default else ''}")
        if not self.interactive:
            return default
        values = [v for v, _ in options]
        while True:
            answer = self._ask(f"{question} [{values.index(default) + 1}] ").strip()
            if not answer:
                return default
            if answer.isdigit() and 1 <= int(answer) <= len(values):
                return values[int(answer) - 1]
            if answer in values:
                return answer


def gb(value: float | None) -> str:
    return "size unknown" if value is None else f"{value:.1f} GB" if value >= 1 else f"{value * 1000:.0f} MB"


def preview_config(config_path: Path, profile: str, template: Path) -> Config:
    """The config this profile would give, without touching the user's file yet."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        if config_path.exists():
            shutil.copyfile(config_path, path)
        write_profile(path, profile, template=template)
        config = load_config(path)
    # As choose_profile() will do: the profile's analyzers replace ones saved from the GUI.
    if (analyzers := profiles.get(profile).overlay.get("engine", {}).get("analyzers")) is not None:
        config.engine.analyzers = list(analyzers)
    return config


def label(d: Download) -> str:
    return f"Whisper {d.name} (faster-whisper)" if d.source == "faster-whisper" else d.name


def downloaded(d: Download) -> bool:
    if d.source == "ollama":
        return ollama.has_model(d.name)
    path = cache_path(d)
    return path is not None and any((path / "snapshots").glob("*/*"))


def grammar_enabled(config: Config) -> bool:
    return "grammar" in config.engine.analyzers


class Setup:
    def __init__(self, args: argparse.Namespace, console: Console, runner: Runner = subprocess.run,
                 detect: Callable[[Path], hardware.Hardware] = hardware.detect):  # fmt: skip
        root = project_root()
        if root is None:
            raise SetupError("setup works in an install folder (from the install script or a git clone)")
        self.args, self.console, self.run, self.root = args, console, runner, root
        self.config_path = args.config or default_config_path()
        self.template = root / "config.example.toml"
        self.hw = detect(root)
        self.python = sys.executable

    # --- steps ----------------------------------------------------------------------------

    def choose_role(self) -> str:
        state = InstallState.load(self.root)
        if role := getattr(self.args, "role", None):
            return role
        default = state.role or "full"
        if not self.console.interactive:
            return default
        self.console.say("\nHow will you use speakcheck?")
        return self.console.choose("  Choose", ROLE_CHOICES, default)

    def choose_profile(self) -> str:
        say = self.console.say
        self.console.step("Your machine")
        for line in self.hw.summary():
            say("  " + line)
        for note in self.hw.notes:
            say(f"  ! {note}")
        recommended = profiles.recommend(self.hw)
        current = load_config(self.config_path).profile if self.config_path.exists() else None
        default = self.args.profile or current or recommended
        self.console.step("Profile")
        options = [(p.name, f"{p.title:<13} {p.description}" + ("  (recommended)" if p.name == recommended else ""))
                   for p in profiles.PROFILES.values()]  # fmt: skip
        if self.args.profile:
            say(f"  Using --profile {self.args.profile}.")
            return self.args.profile
        return self.console.choose("Profile", options, default)

    def show_plan(self, profile: profiles.Profile, accelerator: str, config: Config,
                  downloads: list[Download], ask: bool = True) -> bool:  # fmt: skip
        say = self.console.say
        self.console.step("What will be installed")
        if profile.gpu and self.hw.gpu is None:
            say("  ! No usable GPU found: this profile will run on the CPU, slowly. Consider `cpu`.")
        need = 0.0
        installed = InstallState.load(self.root).accelerator == accelerator and importlib.util.find_spec("torch")
        if installed:
            say(f"  Python packages, PyTorch for {accelerator}: already installed")
        else:
            pkg_download, need = profiles.packages_gb(self.hw.os, accelerator)
            say(f"  Python packages, PyTorch for {accelerator}: about {gb(pkg_download)} to download")
        for d in downloads:
            if d.source == "ollama" and not grammar_enabled(config):
                continue
            if downloaded(d):
                say(f"  {label(d)}: already downloaded")
            else:
                say(f"  {label(d)}: {gb(d.approx_gb)}")
                need += d.approx_gb or 0
        if not grammar_enabled(config):
            say("  Grammar checking is off in this profile (turn it on in the page's settings).")
        say(f"  Disk space needed: about {gb(need)} (free: {gb(self.hw.disk_free_gb)})")
        if need > self.hw.disk_free_gb:
            say("  ! That's more than the free space.")
            return ask and self.console.confirm("Continue anyway?", default=False)
        return ask and self.console.confirm("Continue?")

    def ensure_ollama(self, accelerator: str) -> str | None:
        """Path of the ollama program, installing it if the user agrees; None to skip grammar."""
        say = self.console.say
        if binary := ollama.find():
            return binary
        say("  Grammar checking uses Ollama, which isn't installed.")
        command = ollama.install_command(self.hw.os, accelerator)
        if command and self.console.confirm(f"  Install it now? (runs: {' '.join(command)})"):
            self.run(command, check=False)
            if ollama.boot_service_enabled(self.run) and self.console.confirm(
                    "  Ollama was set to start at every boot; speakcheck starts it only when needed. "
                    "Turn the boot start off?"):  # fmt: skip
                self.run(["sudo", "systemctl", "disable", "--now", "ollama"], check=False)
            if binary := ollama.find():
                return binary
            say("  Ollama isn't found yet (a new terminal may be needed).")
        else:
            say(f"  Install it from {ollama.DOWNLOAD_PAGE}, then run `speakcheck setup` again.")
        return None

    def disable_grammar(self, config: Config) -> None:
        stored = load_user_settings(config.engine.data_dir)
        stored["analyzers"] = [a for a in config.engine.analyzers if a != "grammar"] or ["pronunciation"]
        save_user_settings(config.engine.data_dir, stored)
        self.console.say("  Grammar checking is off for now; turn it on in the page's settings once Ollama works.")

    def download(self, config: Config, downloads: list[Download], ollama_binary: str | None) -> None:
        self.console.step("Downloading models")
        if self.args.no_download:
            self.console.say("  Skipped (--no-download): models download on first use.")
            return
        cmd = [self.python, "-m", "speakcheck.install.download", "--config", str(self.config_path)]
        if self.run(cmd, check=False).returncode != 0:
            self.console.say("  ! Some models failed to download; they will be retried on first use.")
        for d in downloads:
            if d.source == "ollama" and ollama_binary and grammar_enabled(config):
                if ollama.has_model(d.name):
                    self.console.say(f"  {d.name}: already downloaded")
                elif not ollama.pull(d.name, ollama_binary, self.run):
                    self.console.say(f"  ! Downloading {d.name} failed; run `ollama pull {d.name}` later.")

    def launcher(self, menu: bool = True) -> bool:
        """App-menu entry (unless `menu=False`) and the `speakcheck` command; True if the command is usable."""
        from ..desktop import command_on_path, install_command, install_launcher

        say = self.console.say
        self.console.step("App menu and command" if menu else "The speakcheck command")
        question = "  Add speakcheck to your app menu and terminal?" if menu else "  Add the speakcheck command to your terminal?"
        if self.args.no_launcher or not self.console.confirm(question):
            say("  Skipped (`speakcheck desktop-entry` adds the menu entry later).")
            return False
        try:
            if menu:
                say(f"  App menu: {install_launcher(self.python)}")
            say(f"  Command:  {install_command(self.python)}")
        except (OSError, subprocess.SubprocessError) as e:
            say(f"  ! Couldn't add it: {e}")
            return False
        if not command_on_path():
            say("  ! That folder isn't on your PATH yet: open a new terminal (or log in again).")
        return True

    def gpu_works(self) -> bool:
        probe = "import sys, torch; sys.exit(0 if torch.cuda.is_available() or torch.backends.mps.is_available() else 1)"
        return self.run([self.python, "-c", probe], check=False, capture_output=True).returncode == 0

    def fix_amd_gpu(self) -> None:
        gpu = self.hw.gpu
        override = hardware.hsa_override(gpu.gfx if gpu else None)
        say = self.console.say
        if override is None:
            say("  ! PyTorch can't use the AMD GPU; speech models will run on the CPU.")
            return
        env = self.root / ".env"
        say(f"  PyTorch can't use the AMD GPU as-is ({gpu.gfx}); HSA_OVERRIDE_GFX_VERSION={override} usually fixes it.")
        if self.console.confirm(f"  Add it to {env}?"):
            with env.open("a") as f:
                f.write(f"\n# Added by speakcheck setup for {gpu.name} ({gpu.gfx})\nHSA_OVERRIDE_GFX_VERSION={override}\n")
            if not self.gpu_works():
                say("  ! Still not working: check your user is in the render and video groups.")

    def verify(self, accelerator: str) -> bool:
        say = self.console.say
        self.console.step("Checking it works")
        if self.args.no_verify:
            say("  Skipped (--no-verify).")
            return True
        if accelerator != "cpu" or self.hw.os == "darwin":
            if self.gpu_works():
                say("  GPU: working")
            elif accelerator == "rocm":
                self.fix_amd_gpu()
            else:
                say("  ! PyTorch can't use the GPU (check the NVIDIA driver is 525 or newer); using the CPU.")
        say("  Analyzing a test recording (the first run loads the models, which takes a while)…")
        started = time.monotonic()
        cmd = [self.python, "-m", "speakcheck.cli", "analyze", str(SELFTEST_CLIP), "-q", "--format", "json",
               "--config", str(self.config_path)]
        proc = self.run(cmd, check=False, capture_output=True, text=True)
        if proc.returncode == 0:
            say(f"  Test analysis: OK ({time.monotonic() - started:.0f} s)")
            return True
        say("  ! Test analysis failed:")
        for line in (proc.stderr or "").strip().splitlines()[-5:]:
            say(f"    {line}")
        say("  `speakcheck providers` shows what is missing.")
        return False

    # --- flow -----------------------------------------------------------------------------

    # --- client role ----------------------------------------------------------------------

    def _config(self) -> Config:
        """The current config, before setup has written config.toml (the template's defaults)."""
        if self.config_path.exists():
            return load_config(self.config_path)
        return load_config(self.template) if self.template.exists() else load_config()

    def set_remote(self, changes: dict) -> None:
        data_dir = self._config().engine.data_dir
        stored = load_user_settings(data_dir)
        stored["remote"] = {**(stored.get("remote") or {}), **changes}
        save_user_settings(data_dir, stored)

    def server_details(self) -> tuple[str, dict[str, str], str, str]:
        import socket

        say, ask = self.console.say, self.console.text
        current = self._config().remote
        url = getattr(self.args, "server_url", None) or ask("  Server address (e.g. https://speak.example.com):", current.url or "")
        if not url:
            raise SetupError("client mode needs the server's address (--server-url)")
        headers = dict(current.headers)
        for item in getattr(self.args, "server_header", None) or []:
            name, sep, value = item.partition("=")
            if not sep or not name.strip():
                raise SetupError(f"headers look like Name=value, not {item!r}")
            headers[name.strip()] = value.strip()
        if self.console.interactive and not getattr(self.args, "server_header", None):
            say("  Extra headers, if a proxy in front of the server needs them (Name=value; ${VAR} reads .env).")
            while item := ask("  Header (empty when done):"):
                name, _, value = item.partition("=")
                headers[name.strip()] = value.strip()
        invite = getattr(self.args, "invite", None) or ""
        name = getattr(self.args, "device_name", None) or current.device_name or socket.gethostname() or "my computer"
        return url.strip().rstrip("/"), headers, invite, name

    def run_client(self) -> int:
        from ..client import credentials
        from ..client.remote import ServerClient, ServerError, is_insecure

        say = self.console.say
        self.console.total = 4
        self.console.step("Your server")
        url, headers, invite, device = self.server_details()
        data_dir = self._config().engine.data_dir
        client = ServerClient(url, headers)
        try:
            health = client.health()
            say(f"  {url}: speakcheck {health['version']}, analyzers: {', '.join(health['analyzers'])}")
            if is_insecure(url):
                say("  ! This is plain http: your key and recordings cross the network unencrypted. Use https.")
            creds = credentials.load(data_dir, url)
            if not invite and creds is None:
                invite = self.console.text("  Invite code from the server's admin:")
            if self.args.dry_run:
                say("\nDry run: nothing changed.")
                return 0
            if invite:
                data = client.redeem(invite, device)
                creds = credentials.Credentials(url, data["key"], data["device"]["id"], device, data.get("account") or "")
                credentials.save(data_dir, creds)
                say(f"  Connected as '{device}' to the account '{creds.account}'.")
            elif creds is not None:
                say(f"  Already connected as '{creds.device_name}' ({creds.account}).")
            else:
                raise SetupError("an invite code is needed: ask the server's admin (`speakcheck server invite <account>`)")
        except ServerError as e:
            raise SetupError(str(e)) from e
        finally:
            client.close()

        self.console.step("Installing")
        state = InstallState.load(self.root)
        state.role, state.extras = "client", extras_for(None, "client")
        if self.args.installed_version:
            state.version = self.args.installed_version
        sync(self.root, state.extras, self.run)
        state.save(self.root)
        self.set_remote({"mode": "remote", "url": url, "headers": headers, "device_name": device})
        say("  Analysis will run on the server; recordings and history stay on this computer too.")

        command = "speakcheck" if self.launcher() else "uv run speakcheck"
        self.console.step("Checking it works")
        client = ServerClient(url, headers, creds.key)
        try:
            account = client.account()
            say(f"  The server knows this device: account '{account['name']}'.")
            ok = True
        except ServerError as e:
            say(f"  ! {e}")
            ok = False
        finally:
            client.close()
        say("\nDone." if ok else "\nInstalled, with problems (see above).")
        say(f"Start speakcheck from your app menu, or with:  {command} serve --open")
        say("To analyze on this computer instead later: choose it in the page's settings, or run "
            f"`{command} setup --role full`.")  # fmt: skip
        return 0 if ok else 1

    # --- server role ----------------------------------------------------------------------

    def first_account(self, command: str) -> None:
        """Offer to create the first account and an invite, so a device can connect right away."""
        from ..server.db import Database
        from ..server.service import server_dir

        config = self._config()
        db = Database(server_dir(config) / "server.db")
        try:
            if db.accounts() or not self.console.interactive:
                if not db.accounts():
                    self.console.say(f"Add accounts with:  {command} server accounts add <name>")
                return
            if not self.console.confirm("Create the first account now?"):
                return
            name = self.console.text("  Account name:", "me")
            account = db.add_account(name, time.time())
            code = db.add_invite(account.id, time.time(), 7 * 86400)
            self.console.say(f"  Invite for '{name}' (one device, valid 7 days):  {code}")
            self.console.say(f"  More invites:  {command} server invite {name}")
        finally:
            db.close()

    def offer_service(self, command: str) -> None:
        from ..server import os_service

        if self.args.dry_run or not self.console.confirm("Run the server in the background, started with the computer?"):
            self.console.say(f"Start it yourself with:  {command} server serve   (or later: {command} server install-service)")
            return
        cmd = os_service.command(self.python, self.config_path if self.config_path.exists() else None, None, None)
        try:
            self.console.say(f"  Installed: {os_service.install(cmd, self.root, self.run)}")
        except (OSError, subprocess.CalledProcessError) as e:
            self.console.say(f"  ! Couldn't install the service ({e}); run `{command} server serve` instead.")

    def run_all(self) -> int:
        say = self.console.say
        say("speakcheck setup")
        role = self.choose_role()
        if role not in ROLES:
            raise SetupError(f"unknown role {role!r}; choose from {', '.join(ROLES)}")
        if role == "client":
            return self.run_client()
        name = self.choose_profile()
        profile = profiles.get(name)
        accelerator = self.args.accelerator or profiles.accelerator(profile, self.hw)
        config = preview_config(self.config_path, name, self.template)
        downloads = plan_downloads(config)
        if self.args.dry_run:
            self.show_plan(profile, accelerator, config, downloads, ask=False)
            say("\nDry run: nothing changed.")
            return 0
        if not self.show_plan(profile, accelerator, config, downloads):
            say("Nothing changed.")
            return 1

        self.console.step("Installing")
        ollama_binary = None
        if grammar_enabled(config) and any(d.source == "ollama" for d in downloads):
            ollama_binary = None if self.args.no_ollama else self.ensure_ollama(accelerator)
            if ollama_binary is None:
                self.disable_grammar(config)
        state = InstallState.load(self.root)
        was_client = state.role == "client"
        state.accelerator, state.extras, state.role = accelerator, extras_for(accelerator, role), role
        if self.args.installed_version:
            state.version = self.args.installed_version
        sync(self.root, state.extras, self.run)
        state.save(self.root)
        choose_profile(self.config_path, name, template=self.template)
        say(f"  Profile '{name}' saved in {self.config_path}")

        config = load_config(self.config_path)
        if was_client and config.remote.mode == "remote" and self.console.confirm(
                "  Analyze on this computer from now on (instead of on the server)?"):  # fmt: skip
            self.set_remote({"mode": "local"})
        self.download(config, downloads, ollama_binary)
        command = "speakcheck" if self.launcher(menu=role != "server") else "uv run speakcheck"
        ok = self.verify(accelerator)

        say("\nDone." if ok else "\nInstalled, with problems (see above).")
        if role == "server":
            self.first_account(command)
            self.offer_service(command)
            say(f"Run the server with:  {command} server serve --host 0.0.0.0   (put HTTPS in front of it)")
            say(f"Use speakcheck on this computer too, later:  {command} setup --role full")
            return 0 if ok else 1
        say(f"Start speakcheck from your app menu, or with:  {command} serve --open")
        say(f"Change profile any time:  {command} setup   (or in the page's settings)")
        if ok and self.console.interactive and self.console.confirm("Start speakcheck now?"):
            serve = [self.python, "-m", "speakcheck.cli", "serve", "--open", "--config", str(self.config_path)]
            return self.run(serve, check=False).returncode
        return 0 if ok else 1


def run_setup(args: argparse.Namespace, ask: Callable[[str], str] = input) -> int:
    console = Console(interactive=sys.stdin.isatty() and not args.yes, ask=ask)
    try:
        return Setup(args, console).run_all()
    except SpeakcheckError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130
