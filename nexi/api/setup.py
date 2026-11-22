"""First-run defaults: RAM and Minecraft options for this machine."""

from ..game_options import normalize_defaults, write_game_options
from ..instances import instance_game_dir, write_instance
from ..logging_setup import log
from ..system import recommend_setup, total_memory_gb


class SetupApi:
    def setup_defaults(self):
        """Values for the welcome screen plus a recommendation for this PC."""
        total = total_memory_gb()
        recommended = recommend_setup(total, self.RAM_MIN, self.RAM_MAX)
        with self._lock:
            instance = self.active_instance()
            ram = int(self.default_ram)
            game = normalize_defaults(self.default_game_options)
            saved = isinstance(self.default_game_options, dict)
            if instance is not None:
                try:
                    stored = instance.get("ram")
                    if stored is not None:
                        ram = max(self.RAM_MIN,
                                  min(self.RAM_MAX, int(stored)))
                        saved = True
                except (TypeError, ValueError):
                    pass
                if isinstance(instance.get("game_defaults"), dict):
                    game = normalize_defaults(instance["game_defaults"])
                    saved = True
            if not saved:
                # A fresh install starts from what this machine can handle;
                # the values are only stored when the screen is finished.
                ram = recommended["ram"]
                game = dict(recommended["game"])
        return {"ok": True, "total_ram": recommended["total_ram"],
                "ram_min": self.RAM_MIN, "ram_max": self.RAM_MAX,
                "ram": ram, "game": game, "recommended": recommended}

    def apply_setup(self, ram=None, game=None):
        """Store the welcome-screen choices for this and future profiles."""
        try:
            ram = int(ram)
        except (TypeError, ValueError):
            ram = int(self.default_ram)
        ram = max(self.RAM_MIN, min(self.RAM_MAX, ram))
        data = normalize_defaults(
            game if isinstance(game, dict) else self.default_game_options)
        with self._lock:
            self.default_ram = ram
            self.default_game_options = data
            instance = self.active_instance()
            root = None
            if instance is not None:
                try:
                    current_ram = int(instance.get("ram") or self.ram)
                except (TypeError, ValueError):
                    current_ram = int(self.ram)
                # Only rewrite the active profile when the screen actually
                # changes something; walking through an untouched welcome
                # must not replace options the player set in the game.
                current_game = normalize_defaults(
                    instance.get("game_defaults"))
                if current_ram != ram or current_game != data:
                    self.ram = ram
                    instance["ram"] = ram
                    instance["game_defaults"] = data
                    write_instance(instance["_root"], instance)
                    root = instance["_root"]
            self._save()
        if root is not None:
            try:
                write_game_options(instance_game_dir(root), data)
            except OSError as exc:
                log.warning("Could not write options.txt: %s", exc)
        log.info("Setup defaults saved: ram=%s game=%s", ram, data)
        return {"ok": True, "state": self.state(),
                "message": f"Defaults saved: {ram} GB RAM."}
