/* VenTrax sound engine.
 *
 *   VXSound.init({code: 'ABC123'})   load the theme of a game (or the site default)
 *   VXSound.play('hunter_near')      play a random clip of that event (or the synth fallback)
 *   VXSound.stop('intro')            stop a playing event
 *   VXSound.nearby(distanceM)        runner: drives hunter_near / hunter_close from a distance
 *
 * Browsers only allow sound after a tap. We unlock on the very first touch/click anywhere
 * (no popup, no extra button), and the theme + audio files are cached by the service worker.
 */
(function () {
  'use strict';
  var Ctx = window.AudioContext || window.webkitAudioContext;
  var ctx = null, master = null;
  var theme = null, buffers = {}, playing = {}, lastPlayed = {};
  var unlocked = false, pending = [];
  var muted = false, testHook = null;
  try { muted = localStorage.getItem('vx_muted') === '1'; } catch (e) {}

  function now() { return Date.now(); }
  function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

  function ensureCtx() {
    if (!Ctx) return null;
    if (!ctx) {
      ctx = new Ctx();
      master = ctx.createGain();
      master.connect(ctx.destination);
      applyVolume();
    }
    return ctx;
  }
  function applyVolume() {
    if (!master) return;
    var v = theme ? theme.volume / 100 : 0.8;
    master.gain.value = muted ? 0 : v;
  }

  function unlock() {
    var c = ensureCtx();
    if (!c) { unlocked = true; flush(); return; }
    var go = function () {
      unlocked = true; hideTapHint();
      // a silent blip makes iOS Safari treat the context as user-started
      try { var o = c.createOscillator(), g = c.createGain(); g.gain.value = 0; o.connect(g); g.connect(c.destination); o.start(); o.stop(c.currentTime + 0.01); } catch (e) {}
      flush();
      removeUnlockListeners();
    };
    if (c.state === 'suspended') c.resume().then(go, go); else go();
  }
  var unlockEvents = ['touchstart', 'touchend', 'pointerdown', 'click', 'keydown'];
  function removeUnlockListeners() { unlockEvents.forEach(function (e) { document.removeEventListener(e, unlock, true); }); }
  unlockEvents.forEach(function (e) { document.addEventListener(e, unlock, true); });
  // Returning to the tab/app can suspend the context again.
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && ctx && ctx.state === 'suspended' && unlocked) ctx.resume();
  });
  // Sounds asked for before the first tap / before the theme loaded wait a few seconds, then are dropped
  // (a "hunter is near" sound that arrives 2 minutes late is worse than none).
  function later(fn) {
    pending.push({fn: fn, at: now()}); if (pending.length > 12) pending.shift();
    if (!unlocked) showTapHint();
  }
  // A new page starts "locked" again (browser rule). Tell the player once, instead of staying silent.
  var hintEl = null;
  function showTapHint() {
    if (hintEl || !document.body || muted) return;
    hintEl = document.createElement('div');
    hintEl.setAttribute('role', 'button');
    hintEl.textContent = '\uD83D\uDD0A Tik op het scherm voor geluid';
    hintEl.style.cssText = 'position:fixed;left:50%;top:64px;transform:translateX(-50%);z-index:99999;background:rgba(0,0,0,.82);color:#fff;border:1px solid rgba(255,255,255,.25);border-radius:999px;padding:9px 16px;font:600 13px system-ui,sans-serif;box-shadow:0 4px 20px rgba(0,0,0,.5)';
    document.body.appendChild(hintEl);
  }
  function hideTapHint() { if (hintEl) { hintEl.remove(); hintEl = null; } }
  function flush() { var q = pending; pending = []; q.forEach(function (p) { if (now() - p.at < 20000) p.fn(); }); }

  // ---------- loading ----------
  function loadBuffer(url) {
    if (buffers[url]) return buffers[url];
    buffers[url] = fetch(url).then(function (r) {
      if (!r.ok) throw new Error('http ' + r.status);
      return r.arrayBuffer();
    }).then(function (ab) {
      var c = ensureCtx();
      return new Promise(function (res, rej) { c.decodeAudioData(ab, res, rej); });
    }).catch(function () { delete buffers[url]; return null; });
    return buffers[url];
  }
  function preload() {
    if (!theme || !Ctx) return;
    Object.keys(theme.events).forEach(function (ev) {
      theme.events[ev].forEach(function (c) { loadBuffer(c.url); });
    });
  }

  // ---------- synth fallbacks (so a brand-new theme is never silent) ----------
  function osc(type, f0, f1, t0, dur, vol, dest) {
    var c = ctx, o = c.createOscillator(), g = c.createGain();
    o.type = type; o.frequency.setValueAtTime(f0, t0);
    if (f1 && f1 !== f0) o.frequency.exponentialRampToValueAtTime(Math.max(1, f1), t0 + dur);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(Math.max(0.0002, vol), t0 + Math.min(0.03, dur / 4));
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(g); g.connect(dest || master); o.start(t0); o.stop(t0 + dur + 0.05);
    return o;
  }
  function noise(t0, dur, vol, filterType, f0, f1, dest) {
    var c = ctx, n = Math.max(1, Math.floor(c.sampleRate * dur));
    var buf = c.createBuffer(1, n, c.sampleRate), d = buf.getChannelData(0);
    for (var i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    var s = c.createBufferSource(); s.buffer = buf;
    var f = c.createBiquadFilter(); f.type = filterType || 'bandpass';
    f.frequency.setValueAtTime(f0 || 800, t0);
    if (f1) f.frequency.exponentialRampToValueAtTime(f1, t0 + dur);
    f.Q.value = 3;
    var g = c.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(Math.max(0.0002, vol), t0 + dur * 0.3);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    s.connect(f); f.connect(g); g.connect(dest || master); s.start(t0); s.stop(t0 + dur + 0.05);
  }
  function heartbeat(t0, vol, bpm) {
    var gap = 60 / (bpm || 70);
    osc('sine', 62, 38, t0, 0.16, vol);
    osc('sine', 56, 34, t0 + 0.18, 0.2, vol * 0.8);
    return gap;
  }
  function drone(t0, dur, base, vol) {
    osc('sawtooth', base, base * 0.97, t0, dur, vol * 0.5);
    osc('sawtooth', base * 1.5, base * 1.47, t0, dur, vol * 0.25);
    osc('sine', base / 2, base / 2, t0, dur, vol * 0.6);
  }
  function whisper(t0, dur, vol) { noise(t0, dur, vol, 'bandpass', 2600, 1400); noise(t0 + 0.1, dur, vol * 0.7, 'bandpass', 3400, 1800); }
  function bell(t0, f, vol) { osc('sine', f, f, t0, 2.2, vol); osc('sine', f * 2.76, f * 2.76, t0, 1.4, vol * 0.4); osc('sine', f * 5.4, f * 5.4, t0, 0.7, vol * 0.2); }
  function scream(t0, vol) { osc('sawtooth', 900, 1900, t0, 0.5, vol * 0.4); osc('square', 1100, 2300, t0, 0.5, vol * 0.2); noise(t0, 0.5, vol * 0.5, 'bandpass', 2500, 4200); }
  function creak(t0, vol) { osc('sawtooth', 160, 90, t0, 0.9, vol * 0.3); noise(t0, 0.9, vol * 0.3, 'bandpass', 500, 220); }
  function bat(t0, vol) { for (var i = 0; i < 5; i++) noise(t0 + i * 0.07, 0.09, vol * 0.5, 'highpass', 1800, 900); }
  function tick(t0, f, vol) { osc('square', f, f, t0, 0.08, vol); }

  var SYNTH = {
    halloween: {
      intro: function (t, v) { drone(t, 6, 55, v); bell(t + 0.2, 220, v * 0.5); bell(t + 2.8, 196, v * 0.4); whisper(t + 4, 1.6, v * 0.2); },
      countdown_tick: function (t, v) { heartbeat(t, v * 0.9, 90); },
      go: function (t, v) { scream(t, v * 0.7); drone(t, 2.4, 70, v); bell(t, 330, v * 0.5); },
      end: function (t, v) { drone(t, 3.2, 49, v); bell(t, 174, v * 0.6); bell(t + 1.4, 147, v * 0.5); },
      end_win: function (t, v) { bell(t, 392, v * 0.5); bell(t + 0.5, 523, v * 0.5); bell(t + 1, 659, v * 0.5); },
      end_lose: function (t, v) { drone(t, 3.4, 44, v); creak(t + 0.3, v); },
      ambient: function (t, v) { pick([function () { whisper(t, 1.8, v * 0.45); }, function () { creak(t, v); }, function () { bat(t, v); }, function () { bell(t, 130, v * 0.6); }])(); },
      hunter_near: function (t, v) { var g = heartbeat(t, v, 78); heartbeat(t + g, v, 78); whisper(t + 0.2, 1.2, v * 0.25); },
      hunter_close: function (t, v) { var g = heartbeat(t, v * 1.2, 125); heartbeat(t + g, v * 1.2, 125); heartbeat(t + g * 2, v * 1.2, 125); noise(t, 0.6, v * 0.25, 'bandpass', 3000, 1500); },
      zone_out: function (t, v) { drone(t, 1.6, 82, v); osc('sawtooth', 300, 120, t, 1.2, v * 0.3); whisper(t, 1.2, v * 0.3); },
      zone_back: function (t, v) { bell(t, 262, v * 0.4); bell(t + 0.25, 330, v * 0.4); },
      zone_shrink: function (t, v) { drone(t, 2.6, 62, v); osc('sawtooth', 500, 90, t, 2.2, v * 0.25); noise(t, 2.2, v * 0.3, 'bandpass', 600, 150); bell(t + 0.1, 147, v * 0.5); },
      speed_warning: function (t, v) { creak(t, v * 0.9); },
      caught: function (t, v) { scream(t, v); drone(t, 1.8, 60, v * 0.8); },
      mission_new: function (t, v) { bell(t, 330, v * 0.45); bell(t + 0.3, 440, v * 0.45); whisper(t, 1.0, v * 0.2); },
      mission_done: function (t, v) { bell(t, 523, v * 0.5); bell(t + 0.18, 659, v * 0.5); bell(t + 0.36, 784, v * 0.5); },
      lootbox_open: function (t, v) { creak(t, v * 0.8); bell(t + 0.7, 392, v * 0.5); bell(t + 0.95, 523, v * 0.4); },
      offline_start: function (t, v) { noise(t, 1.1, v * 0.4, 'lowpass', 1500, 120); osc('sine', 400, 60, t, 1.0, v * 0.4); },
      offline_end: function (t, v) { noise(t, 0.8, v * 0.35, 'lowpass', 120, 1800); osc('sine', 80, 500, t, 0.7, v * 0.35); },
      target_start: function (t, v) { drone(t, 1.4, 90, v); osc('square', 880, 880, t, 0.12, v * 0.35); osc('square', 880, 880, t + 0.2, 0.12, v * 0.35); osc('square', 880, 880, t + 0.4, 0.12, v * 0.35); },
      target_end: function (t, v) { bell(t, 220, v * 0.5); },
      power: function (t, v) { osc('sawtooth', 200, 800, t, 0.5, v * 0.3); noise(t, 0.5, v * 0.25, 'bandpass', 800, 3000); },
      hazard: function (t, v) { noise(t, 0.7, v * 0.8, 'lowpass', 600, 60); osc('sine', 120, 30, t, 0.7, v * 0.8); },
      pause: function (t, v) { bell(t, 196, v * 0.4); },
      resume: function (t, v) { bell(t, 262, v * 0.4); },
      chat: function (t, v) { tick(t, 520, v * 0.15); },
      photo: function (t, v) { noise(t, 0.1, v * 0.4, 'highpass', 3000, 3000); },
      badge: function (t, v) { bell(t, 523, v * 0.4); bell(t + 0.2, 784, v * 0.4); },
      emergency: function (t, v) { for (var i = 0; i < 4; i++) { osc('square', 800, 800, t + i * 0.3, 0.14, v * 0.4); osc('square', 600, 600, t + i * 0.3 + 0.15, 0.14, v * 0.4); } }
    },
    classic: {
      intro: function (t, v) { tick(t, 392, v * 0.3); tick(t + 0.15, 523, v * 0.3); tick(t + 0.3, 659, v * 0.3); },
      countdown_tick: function (t, v) { tick(t, 660, v * 0.3); },
      go: function (t, v) { tick(t, 523, v * 0.4); tick(t + 0.12, 659, v * 0.4); tick(t + 0.24, 784, v * 0.5); },
      end: function (t, v) { tick(t, 523, v * 0.4); tick(t + 0.2, 392, v * 0.4); tick(t + 0.4, 262, v * 0.5); },
      hunter_near: function (t, v) { tick(t, 440, v * 0.3); tick(t + 0.2, 440, v * 0.3); },
      hunter_close: function (t, v) { tick(t, 880, v * 0.3); tick(t + 0.12, 880, v * 0.3); tick(t + 0.24, 880, v * 0.3); },
      zone_out: function (t, v) { osc('sawtooth', 330, 330, t, 0.4, v * 0.2); },
      zone_shrink: function (t, v) { osc('sawtooth', 600, 200, t, 1.2, v * 0.25); tick(t + 0.1, 440, v * 0.3); tick(t + 0.4, 330, v * 0.3); },
      speed_warning: function (t, v) { osc('sawtooth', 330, 330, t, 0.4, v * 0.2); },
      caught: function (t, v) { tick(t, 330, v * 0.4); tick(t + 0.15, 247, v * 0.4); },
      mission_new: function (t, v) { tick(t, 440, v * 0.3); tick(t + 0.15, 660, v * 0.3); },
      mission_done: function (t, v) { tick(t, 523, v * 0.3); tick(t + 0.1, 659, v * 0.3); tick(t + 0.2, 880, v * 0.35); },
      lootbox_open: function (t, v) { tick(t, 523, v * 0.3); tick(t + 0.1, 659, v * 0.3); tick(t + 0.2, 784, v * 0.4); },
      offline_start: function (t, v) { osc('sine', 600, 200, t, 0.5, v * 0.3); },
      offline_end: function (t, v) { osc('sine', 200, 600, t, 0.5, v * 0.3); },
      target_start: function (t, v) { tick(t, 880, v * 0.35); tick(t + 0.2, 880, v * 0.35); },
      target_end: function (t, v) { tick(t, 440, v * 0.3); },
      power: function (t, v) { osc('sine', 300, 900, t, 0.4, v * 0.3); },
      hazard: function (t, v) { osc('sawtooth', 200, 60, t, 0.5, v * 0.4); },
      pause: function (t, v) { tick(t, 330, v * 0.3); },
      resume: function (t, v) { tick(t, 523, v * 0.3); },
      chat: function (t, v) { tick(t, 660, v * 0.15); },
      photo: function (t, v) { tick(t, 1200, v * 0.15); },
      badge: function (t, v) { tick(t, 523, v * 0.3); tick(t + 0.1, 659, v * 0.3); tick(t + 0.2, 784, v * 0.3); tick(t + 0.3, 1047, v * 0.4); },
      emergency: function (t, v) { for (var i = 0; i < 3; i++) tick(t + i * 0.25, 900, v * 0.4); }
    }
  };
  function synthFor(ev) {
    var set = SYNTH[(theme && theme.skin) || 'classic'] || SYNTH.classic;
    return set[ev] || (SYNTH.classic[ev]);
  }

  // ---------- public API ----------
  function play(ev, opts) {
    opts = opts || {};
    var cooldown = opts.cooldown || 0;
    if (cooldown && lastPlayed[ev] && now() - lastPlayed[ev] < cooldown) return;
    lastPlayed[ev] = now();
    if (testHook) testHook(ev);
    // Visual hook (red pulse etc.) fires even when muted or still locked.
    try { document.dispatchEvent(new CustomEvent('vx:play', {detail: ev})); } catch (e) {}
    if (!theme || !unlocked) { later(function () { doPlay(ev, opts); }); return; }
    doPlay(ev, opts);
  }
  function doPlay(ev, opts) {
    var c = ensureCtx(); if (!c || muted) return;
    var clips = theme.events[ev];
    if (clips && clips.length) {
      var clip = pick(clips);
      loadBuffer(clip.url).then(function (buf) {
        if (!buf) { fallback(ev); return; }
        var offset = opts.offset || 0;
        if (offset >= buf.duration - 0.3) return;   // that part of the clip is already over
        stop(ev);
        var src = c.createBufferSource(); src.buffer = buf;
        var g = c.createGain(); g.gain.value = (clip.volume || 100) / 100;
        src.connect(g); g.connect(master);
        src.start(0, Math.max(0, offset));
        playing[ev] = src;
        src.onended = function () { if (playing[ev] === src) delete playing[ev]; };
      });
      return;
    }
    fallback(ev);
  }
  function fallback(ev) {
    if (!theme || !theme.synth) return;
    var fn = synthFor(ev); if (!fn) return;
    try { fn(ctx.currentTime + 0.02, 0.7); } catch (e) {}
  }
  function stop(ev) {
    var s = playing[ev];
    if (s) { try { s.stop(); } catch (e) {} delete playing[ev]; }
  }
  function stopAll() { Object.keys(playing).forEach(stop); }
  function isPlaying(ev) { return !!playing[ev]; }
  function has(ev) { return !!(theme && theme.events[ev] && theme.events[ev].length); }

  // Runner: distance (m) to the nearest hunter.
  // Rule: the near/close sound plays ONCE when a hunter comes inside the radius. It plays again only after the
  // runner has been outside that radius for REARM_MS (1 minute). Coming back within that minute stays silent.
  var REARM_MS = 60000, HYSTERESIS_M = 10;
  var zones = {near: {armed: true, outsideSince: 0}, close: {armed: true, outsideSince: 0}};
  function track(z, d, radius) {
    if (d <= radius) { z.outsideSince = 0; if (z.armed) { z.armed = false; return true; } return false; }
    if (d > radius + HYSTERESIS_M) {            // clearly outside (a few metres of GPS jitter do not count)
      if (!z.outsideSince) z.outsideSince = now();
      if (now() - z.outsideSince >= REARM_MS) z.armed = true;
    }
    return false;
  }
  function nearby(distM) {
    if (!theme || distM === null || distM === undefined) return;
    var close = track(zones.close, distM, theme.close_m);
    var near = track(zones.near, distM, theme.near_m);
    if (close) { zones.near.armed = false; play('hunter_close'); }
    else if (near) play('hunter_near');
  }

  // Random spooky sounds while a game runs.
  var ambientTimer = null;
  function startAmbient() {
    stopAmbient();
    if (!theme) return;
    var run = function () {
      var lo = theme.ambient_min * 1000, hi = Math.max(lo + 1000, theme.ambient_max * 1000);
      ambientTimer = setTimeout(function () {
        if (document.visibilityState === 'visible') play('ambient');
        run();
      }, lo + Math.random() * (hi - lo));
    };
    if (theme.skin === 'halloween' || has('ambient')) run();
  }
  function stopAmbient() { if (ambientTimer) { clearTimeout(ambientTimer); ambientTimer = null; } }

  function setMuted(m) {
    muted = !!m;
    try { localStorage.setItem('vx_muted', muted ? '1' : '0'); } catch (e) {}
    applyVolume();
    if (muted) stopAll();
    document.dispatchEvent(new CustomEvent('vx:mute', {detail: muted}));
  }

  function init(opts) {
    opts = opts || {};
    var url = opts.theme ? null : (opts.code ? '/api/sound_theme/' + encodeURIComponent(opts.code) : '/api/sound_theme');
    var done = function (t) {
      theme = t; applyVolume(); preload();
      document.dispatchEvent(new CustomEvent('vx:theme', {detail: theme}));
      flush();  // theme is known now: release anything queued before it loaded
    };
    if (opts.theme) { done(opts.theme); return Promise.resolve(opts.theme); }
    return fetch(url, {credentials: 'same-origin'}).then(function (r) { return r.json(); })
      .then(function (t) { done(t); return t; })
      .catch(function () { done({id: 0, skin: 'classic', synth: true, volume: 80, near_m: 120, close_m: 40, ambient_min: 45, ambient_max: 150, events: {}}); });
  }

  window.VXSound = {
    init: init, play: play, stop: stop, stopAll: stopAll, isPlaying: isPlaying, has: has,
    nearby: nearby, startAmbient: startAmbient, stopAmbient: stopAmbient,
    setMuted: setMuted, isMuted: function () { return muted; }, isUnlocked: function () { return unlocked; },
    unlock: unlock, theme: function () { return theme; }, __test_hook: function (fn) { testHook = fn; },
    skin: function () { return (theme && theme.skin) || 'classic'; }
  };
})();
