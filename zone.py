"""Shrinking play field ("storm" like Fortnite). Pure functions, no Flask or database.

A phase announces the next, smaller field `warning_sec` before it takes effect, so everybody can walk to the
new centre; then the field shrinks. The new field always lies inside the current one.
"""
import math
import random

M_LAT = 111320.0
MIN_RADIUS_M = 200.0          # the last field: never smaller than this mean radius (runners must still be able to hide)
FINAL_HOLD_SEC = 300          # the last field stays for at least the last 5 minutes of the game


def _kx(lat):
    return M_LAT * math.cos(math.radians(lat))


def centroid(points):
    return (sum(p['lat'] for p in points) / len(points), sum(p['lng'] for p in points) / len(points))


def mean_radius_m(points):
    c = centroid(points)
    kx = _kx(c[0])
    return sum(math.hypot((p['lat'] - c[0]) * M_LAT, (p['lng'] - c[1]) * kx) for p in points) / len(points)


def point_in_polygon(lat, lng, points):
    inside = False
    j = len(points) - 1
    for i in range(len(points)):
        yi, xi = points[i]['lat'], points[i]['lng']
        yj, xj = points[j]['lat'], points[j]['lng']
        if (xi > lng) != (xj > lng):
            if lat < (yj - yi) * (lng - xi) / ((xj - xi) or 1e-12) + yi:
                inside = not inside
        j = i
    return inside


def _scaled(points, center, factor):
    clat, clng = center
    return [{'lat': round(clat + (p['lat'] - clat) * factor, 7), 'lng': round(clng + (p['lng'] - clng) * factor, 7)}
            for p in points]


def shrink_polygon(points, factor=0.7, rng=None):
    """-> (new_points, centre) with the new field inside `points`.
    The new centre is moved a random distance from the old one (never so far that the new field sticks out)."""
    rng = rng or random.Random()
    c0 = centroid(points)
    if not point_in_polygon(c0[0], c0[1], points):
        return _circle_inside(points, factor)
    r = mean_radius_m(points)
    kx = _kx(c0[0])
    for max_off in (0.45, 0.3, 0.15, 0.0):             # try a wild centre first, then calmer ones
        for _ in range(12 if max_off else 1):
            ang = rng.uniform(0, 2 * math.pi)
            off = rng.uniform(0, max_off * r)
            center = (c0[0] + math.sin(ang) * off / M_LAT, c0[1] + math.cos(ang) * off / kx)
            if not point_in_polygon(center[0], center[1], points):
                continue
            new = _scaled(points, center, factor)
            if all(point_in_polygon(p['lat'], p['lng'], points) for p in new):
                return new, {'lat': round(center[0], 7), 'lng': round(center[1], 7)}
    return _circle_inside(points, factor)


def _edge_distance_m(lat, lng, points):
    kx = _kx(lat)
    px, py = lng * kx, lat * M_LAT
    best = float('inf')
    for i in range(len(points)):
        a, b = points[i], points[(i + 1) % len(points)]
        ax, ay, bx, by = a['lng'] * kx, a['lat'] * M_LAT, b['lng'] * kx, b['lat'] * M_LAT
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best


def _circle_inside(points, factor):
    """Awkward (L-shaped...) fields: the new field becomes a circle around the roomiest spot, so it always fits."""
    lats, lngs = [p['lat'] for p in points], [p['lng'] for p in points]
    best, best_d = None, -1.0
    for i in range(16):
        for j in range(16):
            lat = min(lats) + (max(lats) - min(lats)) * (i + .5) / 16
            lng = min(lngs) + (max(lngs) - min(lngs)) * (j + .5) / 16
            if point_in_polygon(lat, lng, points):
                d = _edge_distance_m(lat, lng, points)
                if d > best_d:
                    best, best_d = (lat, lng), d
    if best is None:
        best, best_d = centroid(points), 10.0
    radius = max(10.0, min(best_d * 0.95, mean_radius_m(points) * factor))
    return regular_polygon(best[0], best[1], radius, 20), {'lat': round(best[0], 7), 'lng': round(best[1], 7)}


def step(state, elapsed, cfg, points, rng=None):
    """Advance the shrink schedule.
    state: {'phase': int, 'pending': None | {'phase', 'points', 'center', 'at'}}   (stored by the caller)
    cfg:   headstart_sec, first_sec, interval_sec, warning_sec, factor  (+ optional min_radius_m, duration_sec, final_hold_sec)
    -> (state, events)   events: ('warn', info) / ('shrink', info) / ('final', info)"""
    state = dict(state or {})
    state.setdefault('phase', 0)
    state.setdefault('pending', None)
    events = []
    nxt = state['phase'] + 1
    t_shrink = cfg['headstart_sec'] + cfg['first_sec'] + (nxt - 1) * cfg['interval_sec']
    lead = cfg['warning_sec']
    if nxt == 1:
        lead = min(lead, cfg['first_sec'] // 2)       # the first announcement may not come before the headstart ends
    pending = state['pending']
    min_r = cfg.get('min_radius_m', MIN_RADIUS_M)
    hold = cfg.get('final_hold_sec', FINAL_HOLD_SEC)

    if pending is None:
        if state.get('final'):
            return state, events
        if elapsed >= t_shrink - lead:
            cur = mean_radius_m(points)
            too_late = bool(cfg.get('duration_sec')) and t_shrink > cfg['duration_sec'] - hold
            if cur <= min_r * 1.02 or too_late:
                state['final'] = True
                events.append(('final', {'phase': state['phase']}))
                return state, events
            factor = max(cfg['factor'], min_r / cur)      # never below the minimum: the last step is smaller
            new_pts, center = shrink_polygon(points, factor, rng)
            pending = state['pending'] = {'phase': nxt, 'points': new_pts, 'center': center, 'at': t_shrink}
            events.append(('warn', {'phase': nxt, 'in_sec': max(0, int(t_shrink - elapsed)), 'points': new_pts,
                                    'center': center}))
    if pending is not None and elapsed >= pending['at']:
        state['phase'] = pending['phase']
        state['pending'] = None
        events.append(('shrink', {'phase': pending['phase'], 'points': pending['points'], 'center': pending['center']}))
    return state, events


def regular_polygon(lat, lng, radius_m, n=24):
    kx = _kx(lat)
    return [{'lat': round(lat + math.sin(2 * math.pi * i / n) * radius_m / M_LAT, 7),
             'lng': round(lng + math.cos(2 * math.pi * i / n) * radius_m / kx, 7)} for i in range(n)]
