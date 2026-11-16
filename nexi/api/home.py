"""Home screen data: recently played worlds across every profile."""

from ..instances import instance_game_dir


class HomeApi:
    def home_state(self):
        """Recent worlds of all profiles, most recently played first.

        A world counts as played when Minecraft has written its level.dat, so
        the save file's mtime is the best available "last played" signal.
        """
        with self._lock:
            instances = list(self.instances)
        worlds = []
        for instance in instances:
            saves = instance_game_dir(instance["_root"]) / "saves"
            if not saves.is_dir():
                continue
            try:
                children = list(saves.iterdir())
            except OSError:
                continue
            for path in children:
                level = path / "level.dat"
                if not path.is_dir() or not level.is_file():
                    continue
                try:
                    modified = level.stat().st_mtime
                except OSError:
                    continue
                worlds.append({
                    "world": path.name,
                    "profile_slug": instance.get("_slug", ""),
                    "profile_name": instance.get("name", ""),
                    "modified": modified,
                })
        worlds.sort(key=lambda item: item["modified"], reverse=True)
        return {"ok": True, "worlds": worlds[:8]}
