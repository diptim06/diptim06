"""Layered GitHub contribution + Ghast animation renderer.

Layers:
    1. ContributionMapLayer  -> real GitHub contribution data
    2. ProjectileLayer       -> simple 3-block projectile
    3. GhastLayer            -> independent 8-direction / 3-emotion sprite
    4. SceneRenderer         -> composites the layers per frame

Sprite atlas expected at ghast/ghast_sprites.png:
    8 columns x 3 rows
    rows: neutral, happy, angry
    columns: front, front-left, left, back-left, back, back-right, right, front-right

The animation intentionally avoids explosions, particles, glow, or decorative FX.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "contributions.json"
SPRITE_FILE = Path(__file__).resolve().parent / "ghast_sprites.png"
OUT_FILE = ROOT / "assets" / "ghast-contributions.gif"

# -----------------------------------------------------------------------------
# Canvas / GitHub-style contribution grid
# -----------------------------------------------------------------------------
CANVAS_W = 780
CANVAS_H = 120
BACKGROUND = "#0d1117"
EMPTY_CELL = "#21262d"
CELL = 11
GAP = 3
STEP = CELL + GAP
ROWS = 7
CELL_RADIUS = 2

# -----------------------------------------------------------------------------
# Animation
# -----------------------------------------------------------------------------
FPS = 8
MOVE_SPEED = 135.0
COOLDOWN_SECONDS = 0.35
RESET_GAP_SECONDS = 3.0
MOUTH_OPEN_SECONDS = 0.20
PROJECTILE_SPEED = 260.0
PROJECTILE_GAP = 2
PROJECTILE_COLORS = ("#9f2d2d", "#d94b3f", "#f58b73")
GHAST_SIZE = 34

# Debug/test: render only the first N targets.
# Set to None once the placement looks right.
PREVIEW_TARGETS: Optional[int] = None

# GIF optimization. Pixel art does not need a full 256-color palette.
GIF_COLORS = 32
PALETTE_SAMPLE_COUNT = 16
RNG_SEED = 24

DIRECTIONS = (
    "front",
    "front_left",
    "left",
    "back_left",
    "back",
    "back_right",
    "right",
    "front_right",
)


@dataclass(frozen=True)
class Day:
    date: str
    count: int
    color: str
    column: int
    row: int


@dataclass(frozen=True)
class Target:
    day: Day
    x: float
    y: float


class SpriteAtlas:
    """Independent Ghast sprite layer backed by the supplied PNG atlas."""

    FRAME_SIZE = 64
    STATES = {"neutral": 0, "happy": 1, "angry": 2}

    def __init__(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"Missing sprite atlas: {path}")
        self.sheet = Image.open(path).convert("RGBA")

        expected_w = self.FRAME_SIZE * 8
        expected_h = self.FRAME_SIZE * 3
        if self.sheet.width < expected_w or self.sheet.height < expected_h:
            raise ValueError(
                f"Sprite atlas must be at least {expected_w}x{expected_h}; "
                f"got {self.sheet.width}x{self.sheet.height}."
            )

        self._cache: dict[tuple[str, int, int], Image.Image] = {}

    def get(self, state: str, direction: int, size: int = GHAST_SIZE) -> Image.Image:
        direction = direction % 8
        key = (state, direction, size)
        if key in self._cache:
            return self._cache[key]

        row = self.STATES[state]
        x0 = direction * self.FRAME_SIZE
        y0 = row * self.FRAME_SIZE
        crop = self.sheet.crop(
            (x0, y0, x0 + self.FRAME_SIZE, y0 + self.FRAME_SIZE)
        )
        sprite = crop.resize((size, size), Image.Resampling.NEAREST)
        self._cache[key] = sprite
        return sprite


class ContributionMapLayer:
    """The contribution calendar layer. Data comes directly from the JSON file."""

    def __init__(self, data_file: Path):
        raw = json.loads(data_file.read_text(encoding="utf-8"))
        weeks = raw["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]

        self.cols = len(weeks)
        self.days: list[Day] = []
        self.by_date: dict[str, Day] = {}

        for col, week in enumerate(weeks):
            for item in week["contributionDays"]:
                day = Day(
                    date=item["date"],
                    count=int(item["contributionCount"]),
                    color=item["color"],
                    column=col,
                    row=int(item["weekday"]),
                )
                self.days.append(day)
                self.by_date[day.date] = day

        self._base = self._build_base()
        self._cache: dict[tuple[str, ...], Image.Image] = {}

    @property
    def active_days(self) -> list[Day]:
        return [day for day in self.days if day.count > 0]

    def origin(self) -> tuple[float, float]:
        width = self.cols * STEP - GAP
        height = ROWS * STEP - GAP
        return (CANVAS_W - width) / 2, (CANVAS_H - height) / 2

    def cell_center(self, col: int, row: int) -> tuple[float, float]:
        x0, y0 = self.origin()
        return (
            x0 + col * STEP + CELL / 2,
            y0 + row * STEP + CELL / 2,
        )

    def _build_base(self) -> Image.Image:
        layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for day in self.days:
            x0, y0 = self.cell_center(day.column, day.row)
            box = (
                int(x0 - CELL / 2),
                int(y0 - CELL / 2),
                int(x0 + CELL / 2),
                int(y0 + CELL / 2),
            )
            draw.rounded_rectangle(box, radius=CELL_RADIUS, fill=EMPTY_CELL)
        return layer

    def _paint_key(self, painted: dict[str, str]) -> tuple[str, ...]:
        return tuple(sorted(f"{date}:{painted[date]}" for date in painted))

    def render(self, painted: dict[str, str]) -> Image.Image:
        """Return a map layer with only the currently revealed contribution colors."""
        key = self._paint_key(painted)
        cached = self._cache.get(key)
        if cached is not None:
            return cached.copy()

        layer = self._base.copy()
        draw = ImageDraw.Draw(layer)
        for date, color in painted.items():
            day = self.by_date[date]
            cx, cy = self.cell_center(day.column, day.row)
            box = (
                int(cx - CELL / 2),
                int(cy - CELL / 2),
                int(cx + CELL / 2),
                int(cy + CELL / 2),
            )
            draw.rounded_rectangle(box, radius=CELL_RADIUS, fill=color)

        self._cache[key] = layer.copy()
        return layer


class ProjectileLayer:
    """Simple 3-block projectile. No glow/explosion/particles."""

    def draw(
        self,
        scene: Image.Image,
        ghast_x: float,
        ghast_y: float,
        target_x: float,
        elapsed: float,
    ) -> None:
        draw = ImageDraw.Draw(scene)
        direction = 1 if target_x >= ghast_x else -1

        start_x = ghast_x + direction * (GHAST_SIZE * 0.45)
        distance = abs(target_x - start_x)
        travel = min(distance, PROJECTILE_SPEED * elapsed)
        head_x = start_x + direction * travel

        # Head + two fading blocks behind it.
        for index, color in enumerate(PROJECTILE_COLORS):
            offset = index * (CELL + PROJECTILE_GAP) * direction
            cx = head_x - offset
            half = CELL / 2
            draw.rectangle(
                (
                    int(cx - half),
                    int(ghast_y - half),
                    int(cx + half),
                    int(ghast_y + half),
                ),
                fill=color,
            )


class GhastLayer:
    """Independent Ghast layer. Position, direction and emotion are all external state."""

    def __init__(self, atlas: SpriteAtlas):
        self.atlas = atlas

    def draw(
        self,
        scene: Image.Image,
        x: float,
        y: float,
        direction: int,
        state: str,
    ) -> None:
        sprite = self.atlas.get(state, direction)
        scene.alpha_composite(
            sprite,
            (int(round(x - sprite.width / 2)), int(round(y - sprite.height / 2))),
        )


class SceneRenderer:
    """Composes map + projectile + Ghast without baking them together."""

    def __init__(self, map_layer: ContributionMapLayer, ghast_layer: GhastLayer):
        self.map_layer = map_layer
        self.ghast_layer = ghast_layer
        self.projectile_layer = ProjectileLayer()

    def render(
        self,
        painted: dict[str, str],
        ghast_x: float,
        ghast_y: float,
        direction: int,
        emotion: str,
        projectile_elapsed: Optional[float] = None,
        projectile_target_x: Optional[float] = None,
    ) -> Image.Image:
        scene = Image.new("RGBA", (CANVAS_W, CANVAS_H), BACKGROUND)

        map_layer = self.map_layer.render(painted)
        scene.alpha_composite(map_layer)

        if projectile_elapsed is not None and projectile_target_x is not None:
            self.projectile_layer.draw(
                scene,
                ghast_x,
                ghast_y,
                projectile_target_x,
                projectile_elapsed,
            )

        self.ghast_layer.draw(scene, ghast_x, ghast_y, direction, emotion)
        return scene.convert("RGB")


def clamp_inside_grid(x: float, y: float, map_layer: ContributionMapLayer) -> tuple[float, float]:
    x0, y0 = map_layer.origin()
    width = map_layer.cols * STEP - GAP
    height = ROWS * STEP - GAP
    half = GHAST_SIZE / 2

    return (
        min(max(x, x0 + half), x0 + width - half),
        min(max(y, y0 + half), y0 + height - half),
    )


def direction_from_delta(dx: float, dy: float) -> int:
    if abs(dx) < 0.001 and abs(dy) < 0.001:
        return 0

    ax, ay = abs(dx), abs(dy)
    if ax >= ay * 1.8:
        return 6 if dx > 0 else 2
    if ay >= ax * 1.8:
        return 4 if dy > 0 else 0
    if dx > 0 and dy < 0:
        return 7
    if dx < 0 and dy < 0:
        return 1
    if dx < 0 and dy > 0:
        return 3
    return 5


def target_staging_position(
    target: Day,
    ghast_x: float,
    map_layer: ContributionMapLayer,
) -> tuple[float, float]:
    tx, ty = map_layer.cell_center(target.column, target.row)
    desired_gap = STEP * 5

    if ghast_x <= tx:
        x = tx - desired_gap
    else:
        x = tx + desired_gap

    return clamp_inside_grid(x, ty, map_layer)


def move_toward(
    x: float,
    y: float,
    tx: float,
    ty: float,
    max_distance: float,
    map_layer: ContributionMapLayer,
) -> tuple[float, float, bool, float, float]:
    dx, dy = tx - x, ty - y
    distance = math.hypot(dx, dy)

    if distance == 0 or distance <= max_distance:
        nx, ny = clamp_inside_grid(tx, ty, map_layer)
        return nx, ny, True, dx, dy

    scale = max_distance / distance
    nx = x + dx * scale
    ny = y + dy * scale
    nx, ny = clamp_inside_grid(nx, ny, map_layer)
    return nx, ny, False, dx, dy


def choose_target(
    map_layer: ContributionMapLayer,
    painted: set[str],
    rng: random.Random,
) -> Optional[Target]:
    candidates = [
        day for day in map_layer.active_days
        if day.date not in painted
    ]
    if not candidates:
        return None

    day = rng.choice(candidates)
    x, y = map_layer.cell_center(day.column, day.row)
    return Target(day=day, x=x, y=y)


def build_animation() -> list[Image.Image]:
    rng = random.Random(RNG_SEED)
    map_layer = ContributionMapLayer(DATA_FILE)
    atlas = SpriteAtlas(SPRITE_FILE)
    scene_renderer = SceneRenderer(map_layer, GhastLayer(atlas))

    if not map_layer.active_days:
        raise RuntimeError("No active contribution days found in contributions.json")

    # Start near the center of the actual contribution grid.
    ghast_x, ghast_y = map_layer.cell_center(map_layer.cols // 2, ROWS // 2)
    ghast_x, ghast_y = clamp_inside_grid(ghast_x, ghast_y, map_layer)
    start_x, start_y = ghast_x, ghast_y
    direction = 0

    painted: dict[str, str] = {}
    paint_order: list[str] = []
    target = choose_target(map_layer, set(), rng)

    phase = "move"
    cooldown = 0.0
    mouth_open = MOUTH_OPEN_SECONDS
    projectile_elapsed = 0.0
    projectile_target_x: Optional[float] = None
    completed = 0
    frame_counter = 0
    happy_elapsed = 0.0
    happy_start_x, happy_start_y = ghast_x, ghast_y
    next_cycle_ready = False

    frames: list[Image.Image] = []

    # Safety bound prevents accidental runaway debug renders.
    safety = 0
    while safety < 25000:
        safety += 1
        dt = 1 / FPS

        if phase == "move":
            if target is None:
                phase = "happy_return"
                continue

            sx, sy = target_staging_position(target.day, ghast_x, map_layer)
            ghast_x, ghast_y, arrived, dx, dy = move_toward(
                ghast_x,
                ghast_y,
                sx,
                sy,
                MOVE_SPEED * dt,
                map_layer,
            )
            if abs(dx) + abs(dy) > 0.01:
                direction = direction_from_delta(dx, dy)

            # Once positioned, face horizontally toward the contribution cell.
            if arrived:
                direction = 6 if target.x >= ghast_x else 2
                mouth_open = MOUTH_OPEN_SECONDS
                phase = "shoot"

            frames.append(
                scene_renderer.render(
                    painted,
                    ghast_x,
                    ghast_y,
                    direction,
                    "neutral",
                )
            )

        elif phase == "shoot":
            assert target is not None
            direction = 6 if target.x >= ghast_x else 2
            mouth_open -= dt

            frames.append(
                scene_renderer.render(
                    painted,
                    ghast_x,
                    ghast_y,
                    direction,
                    "angry",
                )
            )

            if mouth_open <= 0:
                projectile_elapsed = 0.0
                projectile_target_x = target.x
                phase = "projectile"

        elif phase == "projectile":
            assert target is not None
            direction = 6 if target.x >= ghast_x else 2
            projectile_elapsed += dt

            start_projectile_x = ghast_x + (1 if direction == 6 else -1) * (GHAST_SIZE * 0.45)
            distance = abs(target.x - start_projectile_x)

            frames.append(
                scene_renderer.render(
                    painted,
                    ghast_x,
                    ghast_y,
                    direction,
                    "angry",
                    projectile_elapsed,
                    projectile_target_x,
                )
            )

            if projectile_elapsed * PROJECTILE_SPEED >= distance:
                # Impact has exactly one effect: reveal the real contribution color.
                painted[target.day.date] = target.day.color
                paint_order.append(target.day.date)
                completed += 1
                projectile_target_x = None

                reached_limit = PREVIEW_TARGETS is not None and completed >= PREVIEW_TARGETS
                all_done = completed >= len(map_layer.active_days)

                if reached_limit or all_done:
                    happy_elapsed = 0.0
                    happy_start_x, happy_start_y = ghast_x, ghast_y
                    phase = "happy_return"
                else:
                    cooldown = COOLDOWN_SECONDS
                    target = choose_target(map_layer, set(painted), rng)
                    phase = "cooldown"

        elif phase == "cooldown":
            cooldown -= dt

            # Keep roaming subtly while waiting for the next shot.
            drift_direction = 1 if math.sin(frame_counter / 18) >= 0 else -1
            drift_x = ghast_x + drift_direction * STEP * 1.5
            drift_y = ghast_y + math.sin(frame_counter / 18) * STEP * 0.5
            drift_x, drift_y = clamp_inside_grid(drift_x, drift_y, map_layer)

            ghast_x, ghast_y, _, dx, dy = move_toward(
                ghast_x,
                ghast_y,
                drift_x,
                drift_y,
                MOVE_SPEED * dt,
                map_layer,
            )
            if abs(dx) + abs(dy) > 0.01:
                direction = direction_from_delta(dx, dy)

            frames.append(
                scene_renderer.render(
                    painted,
                    ghast_x,
                    ghast_y,
                    direction,
                    "neutral",
                )
            )

            if cooldown <= 0:
                phase = "move"

        elif phase == "happy_return":
            # This is the seamless loop bridge: keep the Ghast happy for a
            # continuous ~3-second reset window while returning to its exact
            # starting position. Contribution cells disappear one-by-one
            # throughout the same window. There is no teleport/reset frame.
            happy_elapsed += dt
            progress = min(1.0, happy_elapsed / RESET_GAP_SECONDS)
            smooth = progress * progress * (3.0 - 2.0 * progress)

            ghast_x = happy_start_x + (start_x - happy_start_x) * smooth
            ghast_y = happy_start_y + (start_y - happy_start_y) * smooth
            ghast_x, ghast_y = clamp_inside_grid(ghast_x, ghast_y, map_layer)

            # Face the direction the Ghast is actually travelling on this
            # frame, so the happy sprite never appears to fly backwards.
            return_dx = start_x - ghast_x
            return_dy = start_y - ghast_y
            if abs(return_dx) + abs(return_dy) > 0.01:
                direction = direction_from_delta(return_dx, return_dy)

            # Spread the cell reset over the full 3-second happy window.
            if paint_order:
                cells_to_keep = len(paint_order)
                total_cells = max(1, completed)
                desired_removed = min(
                    total_cells,
                    int((progress ** 1.05) * total_cells),
                )
                while len(paint_order) > total_cells - desired_removed:
                    date = paint_order.pop(0)
                    painted.pop(date, None)

            frames.append(
                scene_renderer.render(
                    painted,
                    ghast_x,
                    ghast_y,
                    direction,
                    "happy",
                )
            )

            if progress >= 1.0:
                # Exact loop hand-off: no teleport, no blank/reset frame.
                # The next frame starts another normal move toward a fresh
                # target from the same starting position.
                painted.clear()
                paint_order.clear()
                completed = 0
                target = choose_target(map_layer, set(), rng)
                phase = "move"
                happy_elapsed = 0.0

        frame_counter += 1

        # End a preview after the happy/reset cycle has visibly completed.
        if PREVIEW_TARGETS is not None and completed == 0 and not painted and safety > 400:
            break

    if not frames:
        raise RuntimeError("Renderer produced no frames.")

    return frames


def build_global_palette(frames: list[Image.Image]) -> Image.Image:
    """Build one shared GIF palette from representative animation frames."""
    if not frames:
        raise RuntimeError("Cannot build a palette from zero frames.")

    count = min(PALETTE_SAMPLE_COUNT, len(frames))
    if count == 1:
        samples = [frames[0]]
    else:
        indices = [round(i * (len(frames) - 1) / (count - 1)) for i in range(count)]
        samples = [frames[i] for i in indices]

    # Downscale samples before palette generation. This keeps palette creation
    # fast while preserving the fixed pixel-art colors used by the animation.
    thumb_w = min(600, CANVAS_W)
    thumb_h = max(1, round(CANVAS_H * thumb_w / CANVAS_W))
    thumbs = [frame.resize((thumb_w, thumb_h), Image.Resampling.NEAREST) for frame in samples]
    sheet = Image.new("RGB", (thumb_w, thumb_h * len(thumbs)))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, (0, index * thumb_h))

    return sheet.quantize(
        colors=GIF_COLORS,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )


def quantize_and_deduplicate(
    frames: list[Image.Image],
) -> tuple[list[Image.Image], list[int]]:
    """Use one shared palette and collapse identical adjacent frames."""
    palette = build_global_palette(frames)
    encoded: list[Image.Image] = []
    durations: list[int] = []
    base_duration = int(round(1000 / FPS))

    for frame in frames:
        quantized = frame.quantize(
            palette=palette,
            dither=Image.Dither.NONE,
        )

        if encoded and quantized.tobytes() == encoded[-1].tobytes():
            durations[-1] += base_duration
        else:
            encoded.append(quantized)
            durations.append(base_duration)

    return encoded, durations


def main() -> None:
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    frames = build_animation()
    encoded_frames, durations = quantize_and_deduplicate(frames)

    encoded_frames[0].save(
        OUT_FILE,
        save_all=True,
        append_images=encoded_frames[1:],
        duration=durations,
        loop=0,
        # Keep unchanged pixels from the previous frame so Pillow can store
        # only the changed rectangle instead of clearing the whole canvas.
        disposal=1,
        optimize=True,
    )

    size_mb = OUT_FILE.stat().st_size / (1024 * 1024)
    print(
        f"Rendered {len(frames)} frames -> {len(encoded_frames)} GIF frames "
        f"-> {OUT_FILE} ({size_mb:.2f} MB)"
    )


if __name__ == "__main__":
    main()
