"""Piecewise-linear gain envelopes (music ducking, scene gating). Pure.

The resolver produces breakpoints; the export turns them into an FFmpeg ``volume`` expression and the preview
into WebAudio gain values, so both follow the same curve.
"""
from __future__ import annotations

import bisect

Breakpoints = list[list[float]]          # [[t, gain], ...], t ascending


def evaluate(points: Breakpoints, t: float) -> float:
    if not points:
        return 1.0
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    i = bisect.bisect_right([p[0] for p in points], t)
    (t0, g0), (t1, g1) = points[i - 1], points[i]
    return g0 if t1 <= t0 else g0 + (g1 - g0) * (t - t0) / (t1 - t0)


def simplify(points: Breakpoints) -> Breakpoints:
    out: Breakpoints = []
    for t, g in points:
        t, g = round(t, 4), round(g, 5)
        if out and abs(out[-1][0] - t) < 1e-6:
            out[-1][1] = g
            continue
        if len(out) >= 2 and abs(out[-1][1] - g) < 1e-6 and abs(out[-2][1] - g) < 1e-6:
            out[-1][0] = t
            continue
        out.append([t, g])
    return out


def multiply(a: Breakpoints, b: Breakpoints) -> Breakpoints:
    times = sorted({p[0] for p in a} | {p[0] for p in b})
    return simplify([[t, evaluate(a, t) * evaluate(b, t)] for t in times])


def merge_intervals(spans: list[tuple[float, float]], join_gap: float) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(spans):
        if out and a - out[-1][1] <= join_gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def duck(spans: list[tuple[float, float]], depth_db: float, attack_s: float, release_s: float,
         start: float, end: float) -> Breakpoints:
    """1.0 outside speech, ``depth_db`` below it during speech, with linear ramps (attack before, release after)."""
    low = 10 ** (depth_db / 20)
    spans = merge_intervals(spans, attack_s + release_s)
    pts: Breakpoints = [[start, 1.0]]
    for a, b in spans:
        a0 = max(start, a - attack_s)
        b1 = min(end, b + release_s)
        if b1 <= a0:
            continue
        pts += [[a0, 1.0], [max(a0, a), low], [min(b1, b), low], [b1, 1.0]]
    pts.append([end, 1.0])
    return simplify(pts)


def gate(windows: list[tuple[float, float, bool]], ramp_s: float, start: float, end: float) -> Breakpoints:
    """1.0 in windows that are on, 0.0 in windows that are off, ramping ``ramp_s`` at each change."""
    pts: Breakpoints = []
    prev = None
    for a, b, on in windows:
        g = 1.0 if on else 0.0
        if prev is None:
            pts.append([a, g])
        elif prev != g:
            pts += [[max(start, a - ramp_s / 2), prev], [min(end, a + ramp_s / 2), g]]
        prev = g
        pts.append([b, g])
    return simplify(pts) if pts else [[start, 1.0], [end, 1.0]]


def ffmpeg_expr(points: Breakpoints) -> str:
    """A ``volume`` filter expression (use with eval=frame) that follows the breakpoints in time ``t``."""
    if not points:
        return "1"
    if all(abs(p[1] - points[0][1]) < 1e-6 for p in points):
        return f"{points[0][1]:.5f}"
    terms = [f"lt(t,{points[0][0]:.4f})*{points[0][1]:.5f}"]
    for (t0, g0), (t1, g1) in zip(points, points[1:]):
        if t1 <= t0:
            continue
        if abs(g1 - g0) < 1e-6:
            terms.append(f"gte(t,{t0:.4f})*lt(t,{t1:.4f})*{g0:.5f}")
        else:
            slope = (g1 - g0) / (t1 - t0)
            terms.append(f"gte(t,{t0:.4f})*lt(t,{t1:.4f})*({g0:.5f}+{slope:.6f}*(t-{t0:.4f}))")
    terms.append(f"gte(t,{points[-1][0]:.4f})*{points[-1][1]:.5f}")
    return "+".join(terms)
