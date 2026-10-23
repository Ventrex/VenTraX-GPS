"""
VenTrax bots: map data, walking routes and a simple hunter/runner brain.

Nothing in here touches the database or Flask, so it can be tested on its own.

How it works
  1. Terrain: OpenStreetMap data of the play area is downloaded (Overpass API, configurable so you can
     point it at your own server) and drawn onto a grid of ~6 m cells:
        blocked  = water, buildings, railways, motorways, outside the play field
        brush    = woods, scrub, heath, wetland  (walkable, but at half speed)
        normal   = everything else
        paths    = footpaths, roads and bridges are always walkable, even over water/rails/brush
  2. Routes: A* over that grid (8 directions, no cutting corners).
  3. Brain: runners flee to a spot far from the hunters, hunters chase the nearest runner.

Known limits (be honest about them in the UI): garden fences/walls are not mapped, so bots may walk through
gardens; OSM can be wrong or out of date; bots know where everyone is; and they never use offline/pause.
"""
import hashlib
import heapq
import json
import math
import os
import random
import time
from array import array

from PIL import Image, ImageDraw

CELL_M = 6.0
M_LAT = 111320.0                      # metres per degree of latitude
MAX_CELLS = 700_000                   # cap so a huge play field cannot eat all memory
BLOCKED, NORMAL, BRUSH = 0, 1, 2

# Walking speed in m/s per difficulty (easy = slow stroll, medium = normal walk, hard = brisk walk, never running)
SPEEDS = {'easy': 1.0, 'medium': 1.4, 'hard': 2.0, 'custom': 1.4}
BRUSH_SPEED_FACTOR = 0.5              # through bushes: half speed

WALKABLE_HIGHWAYS = {
    'footway', 'path', 'pedestrian', 'cycleway', 'steps', 'track', 'service', 'residential', 'living_street',
    'unclassified', 'tertiary', 'tertiary_link', 'secondary', 'secondary_link', 'primary', 'primary_link',
    'road', 'bridleway', 'corridor',
}
BLOCKED_HIGHWAYS = {'motorway', 'motorway_link', 'trunk', 'trunk_link'}
BRUSH_NATURAL = {'wood', 'scrub', 'heath', 'wetland'}
BRUSH_LANDUSE = {'forest'}
WATER_LINES_WIDE = {'river', 'canal'}
WATER_LINES_NARROW = {'stream'}


# --------------------------------------------------------------------------------------- geometry
def haversine(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def destination(lat, lon, meters, bearing_deg):
    b = math.radians(bearing_deg)
    return (lat + (meters * math.cos(b)) / M_LAT,
            lon + (meters * math.sin(b)) / (M_LAT * math.cos(math.radians(lat))))


def bbox_of(points, margin_m=150.0):
    """points: [(lat, lon)] -> (south, west, north, east) with a margin."""
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lat_mid = (min(lats) + max(lats)) / 2
    dlat = margin_m / M_LAT
    dlon = margin_m / (M_LAT * math.cos(math.radians(lat_mid)))
    return (min(lats) - dlat, min(lons) - dlon, max(lats) + dlat, max(lons) + dlon)


# --------------------------------------------------------------------------------------- terrain
class Terrain:
    def __init__(self, bbox, cell_m=CELL_M, degraded=False):
        s, w, n, e = bbox
        self.bbox = bbox
        self.lat_n, self.lon_w = n, w
        self.kx = M_LAT * math.cos(math.radians((n + s) / 2))   # metres per degree of longitude
        width_m, height_m = (e - w) * self.kx, (n - s) * M_LAT
        cell = cell_m
        while (width_m / cell) * (height_m / cell) > MAX_CELLS:
            cell *= 1.25
        self.cell = cell
        self.w = max(1, int(math.ceil(width_m / cell)))
        self.h = max(1, int(math.ceil(height_m / cell)))
        self.cost = bytearray([NORMAL]) * (self.w * self.h)
        self.degraded = degraded         # True = map data was unavailable, everything is open ground

    def to_xy(self, lat, lon):
        return (int((lon - self.lon_w) * self.kx / self.cell), int((self.lat_n - lat) * M_LAT / self.cell))

    def to_latlon(self, x, y):
        return (self.lat_n - (y + 0.5) * self.cell / M_LAT, self.lon_w + (x + 0.5) * self.cell / self.kx)

    def inside(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    def at(self, x, y):
        return self.cost[y * self.w + x] if self.inside(x, y) else BLOCKED

    def nearest_walkable(self, x, y, max_r=25):
        """The closest walkable cell to (x, y) - GPS error can put someone 'in' a building or the water."""
        x = min(max(x, 0), self.w - 1)
        y = min(max(y, 0), self.h - 1)
        if self.at(x, y):
            return x, y
        for r in range(1, max_r + 1):
            best = None
            for dx in range(-r, r + 1):
                for dy in (-r, r):
                    for cx, cy in ((x + dx, y + dy), (x + dy, y + dx)):
                        if self.at(cx, cy):
                            d = (cx - x) ** 2 + (cy - y) ** 2
                            if best is None or d < best[0]:
                                best = (d, cx, cy)
            if best:
                return best[1], best[2]
        return None

    def random_walkable(self, rng, near=None, min_m=0.0, max_m=None, tries=200):
        """Random walkable cell, optionally between min_m and max_m metres from `near` (x, y)."""
        for _ in range(tries):
            if near is None:
                x, y = rng.randrange(self.w), rng.randrange(self.h)
            else:
                ang = rng.uniform(0, 2 * math.pi)
                dist = rng.uniform(min_m, max_m or min_m + 100) / self.cell
                x, y = int(near[0] + math.cos(ang) * dist), int(near[1] + math.sin(ang) * dist)
            if self.at(x, y):
                return x, y
        return None


# --------------------------------------------------------------------------------------- map download
def overpass_query(bbox):
    s, w, n, e = bbox
    b = f'({s:.6f},{w:.6f},{n:.6f},{e:.6f})'
    return (
        '[out:json][timeout:40];('
        f'way["natural"~"^(water|wood|scrub|heath|wetland)$"]{b};'
        f'way["landuse"~"^(forest|reservoir|basin)$"]{b};'
        f'way["waterway"~"^(river|riverbank|stream|canal)$"]{b};'
        f'way["building"]{b};'
        f'way["highway"]{b};'
        f'way["railway"~"^(rail|light_rail|narrow_gauge|preserved)$"]{b};'
        f'relation["type"="multipolygon"]["natural"~"^(water|wood|scrub|heath|wetland)$"]{b};'
        f'relation["type"="multipolygon"]["landuse"~"^(forest|reservoir|basin)$"]{b};'
        f'relation["type"="multipolygon"]["building"]{b};'
        ');out geom;')


def fetch_elements(bbox, overpass_url, cache_dir=None, ttl=7 * 86400, http_post=None, timeout=60):
    """Overpass JSON elements for a bbox, cached on disk (the same play field is reused for days)."""
    key = hashlib.sha1(('v1' + overpass_query(bbox)).encode()).hexdigest()[:20]
    path = os.path.join(cache_dir, f'{key}.json') if cache_dir else None
    if path and os.path.isfile(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    if http_post is None:
        import requests
        http_post = requests.post
    resp = http_post(overpass_url, data={'data': overpass_query(bbox)}, timeout=timeout,
                     headers={'User-Agent': 'VenTrax-GPS bots (self-hosted game)'})
    resp.raise_for_status()
    elements = resp.json().get('elements', [])
    if path:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(elements, fh)
    return elements


def _geom(el):
    return [(p['lat'], p['lon']) for p in el.get('geometry', []) if p]


def assemble_rings(segments):
    """Join way pieces of a multipolygon into closed rings (greedy, by matching end points)."""
    segs = [list(s) for s in segments if len(s) >= 2]
    rings = []
    while segs:
        ring = segs.pop()
        changed = True
        while changed and ring[0] != ring[-1]:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]
                elif s[-1] == ring[-1]:
                    ring += s[::-1][1:]
                elif s[-1] == ring[0]:
                    ring = s[:-1] + ring
                elif s[0] == ring[0]:
                    ring = s[::-1][:-1] + ring
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def build_terrain(elements, bbox, playfield=None, cell_m=CELL_M):
    """Draw OSM elements onto a Terrain. playfield: [(lat, lon)] polygon, everything outside is blocked."""
    t = Terrain(bbox, cell_m)
    img = Image.new('L', (t.w, t.h), NORMAL)
    draw = ImageDraw.Draw(img)

    def px(points):
        return [t.to_xy(lat, lon) for lat, lon in points]

    def poly(points, value):
        xy = px(points)
        if len(xy) >= 3:
            draw.polygon(xy, fill=value, outline=value)

    def line(points, value, width=1):
        xy = px(points)
        if len(xy) >= 2:
            draw.line(xy, fill=value, width=width)

    brush_polys, block_polys, inner_polys = [], [], []
    water_lines, rail_lines, bad_roads, walk_lines = [], [], [], []

    for el in elements:
        tags = el.get('tags') or {}
        kind = None
        if tags.get('natural') in BRUSH_NATURAL and tags.get('natural') != 'water' or tags.get('landuse') in BRUSH_LANDUSE:
            kind = 'brush'
        if tags.get('natural') == 'water' or tags.get('landuse') in ('reservoir', 'basin') \
                or tags.get('waterway') == 'riverbank' or 'building' in tags:
            kind = 'block'

        if el.get('type') == 'relation':
            outers, inners = [], []
            for m in el.get('members', []):
                g = _geom(m)
                if m.get('role') == 'inner':
                    inners.append(g)
                elif m.get('role') in ('outer', ''):
                    outers.append(g)
            for ring in assemble_rings(outers):
                (brush_polys if kind == 'brush' else block_polys).append(ring)
            if kind:
                inner_polys += assemble_rings(inners)
            continue

        g = _geom(el)
        if len(g) < 2:
            continue
        closed = g[0] == g[-1] and len(g) >= 4
        hw, rw, ww = tags.get('highway'), tags.get('railway'), tags.get('waterway')
        if hw:
            if hw in BLOCKED_HIGHWAYS:
                bad_roads.append(g)
            elif hw in WALKABLE_HIGHWAYS and tags.get('access') not in ('no', 'private') \
                    and tags.get('foot') != 'no':
                walk_lines.append(g)
        elif rw:
            if tags.get('tunnel') != 'yes':
                rail_lines.append(g)
        elif ww in WATER_LINES_WIDE | WATER_LINES_NARROW:
            if tags.get('tunnel') != 'yes' and tags.get('culvert') != 'yes':
                water_lines.append((g, 3 if ww in WATER_LINES_WIDE else 1))
        elif kind and closed:
            (brush_polys if kind == 'brush' else block_polys).append(g)

    for ring in brush_polys:
        poly(ring, BRUSH)
    for ring in block_polys:
        poly(ring, BLOCKED)
    for ring in inner_polys:
        poly(ring, NORMAL)                      # islands / courtyards inside a lake or building
    for g, width in water_lines:
        line(g, BLOCKED, width)
    for g in rail_lines:
        line(g, BLOCKED, 1)
    for g in bad_roads:
        line(g, BLOCKED, 2)
    for g in walk_lines:                         # last: bridges, crossings and forest paths stay walkable
        line(g, NORMAL, 1)

    if playfield and len(playfield) >= 3:
        mask = Image.new('L', (t.w, t.h), 0)
        ImageDraw.Draw(mask).polygon(px(playfield), fill=255, outline=255)
        img = Image.composite(img, Image.new('L', (t.w, t.h), BLOCKED), mask)

    t.cost = bytearray(img.tobytes())
    return t


def open_terrain(bbox, playfield=None):
    """Fallback when no map data is available: open ground (still limited to the play field)."""
    t = Terrain(bbox, degraded=True)
    if playfield and len(playfield) >= 3:
        img = Image.new('L', (t.w, t.h), BLOCKED)
        ImageDraw.Draw(img).polygon([t.to_xy(a, b) for a, b in playfield], fill=NORMAL, outline=NORMAL)
        t.cost = bytearray(img.tobytes())
    return t


def load_terrain(bbox, overpass_url, playfield=None, cache_dir=None, http_post=None):
    """Terrain from OpenStreetMap, or open ground (degraded=True) if the download fails."""
    try:
        return build_terrain(fetch_elements(bbox, overpass_url, cache_dir, http_post=http_post), bbox, playfield)
    except Exception:
        return open_terrain(bbox, playfield)


# --------------------------------------------------------------------------------------- routes
_DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
         (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]


def astar(t, start, goal, max_nodes=250_000):
    """Cheapest walking route as a list of cells, or None. Brush counts double, blocked cells never,
    and diagonal steps may not squeeze between two blocked cells."""
    if not (t.at(*start) and t.at(*goal)):
        return None
    if start == goal:
        return [start]
    w = t.w
    sx, sy = start
    gx, gy = goal
    g = array('f', [float('inf')]) * (w * t.h)
    parent = array('i', [-1]) * (w * t.h)
    s_idx, g_idx = sy * w + sx, gy * w + gx
    g[s_idx] = 0.0

    def h(x, y):
        dx, dy = abs(x - gx), abs(y - gy)
        return (dx + dy) + (1.4142 - 2) * min(dx, dy)

    heap = [(h(sx, sy), s_idx)]
    cost = t.cost
    expanded = 0
    while heap:
        f, idx = heapq.heappop(heap)
        if idx == g_idx:
            out = []
            while idx != -1:
                out.append((idx % w, idx // w))
                idx = parent[idx]
            return out[::-1]
        x, y = idx % w, idx // w
        if f - h(x, y) > g[idx] + 1e-2:
            continue
        expanded += 1
        if expanded > max_nodes:
            return None
        for dx, dy, step in _DIRS:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < t.h):
                continue
            c = cost[ny * w + nx]
            if not c:
                continue
            if dx and dy and not cost[y * w + nx] and not cost[ny * w + x]:
                continue                        # no squeezing through a diagonal gap
            nidx = ny * w + nx
            ng = g[idx] + step * (BRUSH_SPEED_FACTOR ** -1 if c == BRUSH else 1.0)
            if ng < g[nidx]:
                g[nidx] = ng
                parent[nidx] = idx
                heapq.heappush(heap, (ng + h(nx, ny), nidx))
    return None


def route_latlon(t, start_ll, goal_ll):
    """Walking route between two coordinates as [(lat, lon, speed_factor)] or None."""
    s = t.nearest_walkable(*t.to_xy(*start_ll))
    e = t.nearest_walkable(*t.to_xy(*goal_ll))
    if not s or not e:
        return None
    cells = astar(t, s, e)
    if not cells:
        return None
    return [(*t.to_latlon(x, y), BRUSH_SPEED_FACTOR if t.at(x, y) == BRUSH else 1.0) for x, y in cells]


# --------------------------------------------------------------------------------------- brain
class Bot:
    """One bot walking along a route. All times in seconds, positions in degrees."""

    def __init__(self, user_id, role, lat, lon, difficulty='medium', seed=None):
        self.user_id, self.role = user_id, role
        self.lat, self.lon = lat, lon
        self.speed = SPEEDS.get(difficulty, SPEEDS['medium'])
        self.route = []              # [(lat, lon, factor)]
        self.next_i = 0
        self.replan_at = 0.0
        self.rng = random.Random(seed)
        self.moved_m = 0.0
        self.last_speed = 0.0

    def set_route(self, route):
        self.route = route or []
        self.next_i = 1 if len(self.route) > 1 else len(self.route)

    def walk(self, dt):
        """Advance along the route for dt seconds. Returns metres moved."""
        budget, moved = dt, 0.0
        while budget > 1e-6 and self.next_i < len(self.route):
            tlat, tlon, factor = self.route[self.next_i]
            seg = haversine(self.lat, self.lon, tlat, tlon)
            v = self.speed * factor
            need = seg / v if v else 0
            if need <= budget:
                self.lat, self.lon = tlat, tlon
                budget -= need
                moved += seg
                self.next_i += 1
            else:
                f = (v * budget) / seg
                self.lat += (tlat - self.lat) * f
                self.lon += (tlon - self.lon) * f
                moved += v * budget
                budget = 0
        self.moved_m += moved
        self.last_speed = moved / dt if dt else 0.0
        return moved

    @property
    def arrived(self):
        return self.next_i >= len(self.route)


def pick_flee_goal(t, bot, hunters, rng, tries=60, radius_m=450):
    """Spot on the map that is far from every hunter and not too far for the bot to reach."""
    here = t.to_xy(bot.lat, bot.lon)
    base = min((haversine(bot.lat, bot.lon, h[0], h[1]) for h in hunters), default=0.0)
    best, best_score = None, -1e9
    for _ in range(tries):
        c = t.random_walkable(rng, near=here, min_m=60, max_m=radius_m)
        if not c:
            continue
        lat, lon = t.to_latlon(*c)
        d_h = min((haversine(lat, lon, h[0], h[1]) for h in hunters), default=base + 100)
        if d_h < base:                       # never run towards the hunters
            continue
        score = d_h - 0.25 * haversine(bot.lat, bot.lon, lat, lon)
        if score > best_score:
            best, best_score = (lat, lon), score
    return best


def plan(t, bot, others, now, rng=None):
    """Decide (and compute) a new route for a bot when it is time to.
    others: for a runner = hunter positions [(lat, lon)], for a hunter = runner positions."""
    rng = rng or bot.rng
    if now < bot.replan_at and not bot.arrived:
        return False
    if bot.role == 'hunter':
        if not others:
            bot.set_route([]); bot.replan_at = now + 10
            return True
        target = min(others, key=lambda p: haversine(bot.lat, bot.lon, p[0], p[1]))
        bot.set_route(route_latlon(t, (bot.lat, bot.lon), target))
        near = haversine(bot.lat, bot.lon, target[0], target[1]) < 40
        bot.replan_at = now + (3 if near else 12)      # keep a closer eye on a runner that is almost caught
        return True
    # runner
    goal = pick_flee_goal(t, bot, others, rng) if others else None
    if goal is None:                          # nobody to flee from: wander a little
        c = t.random_walkable(rng, near=t.to_xy(bot.lat, bot.lon), min_m=40, max_m=200)
        goal = t.to_latlon(*c) if c else None
    bot.set_route(route_latlon(t, (bot.lat, bot.lon), goal) if goal else [])
    bot.replan_at = now + (25 if goal else 8)
    return True
