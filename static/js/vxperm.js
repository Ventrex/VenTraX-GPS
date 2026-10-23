/* One-time permissions for this phone.
 *
 * Browsers decide for themselves how long a "Allow" is remembered; a website cannot switch the
 * popup off. What we *can* do - and do here - is:
 *   1. ask exactly once, in a friendly setup step, instead of in the middle of a game;
 *   2. never ask again while the permission is still granted (we check first, silently);
 *   3. remember on this phone that the setup is done;
 *   4. register the service worker + offer "install as app", because installed apps keep
 *      their location/sound permission far more reliably than a browser tab does.
 */
(function () {
  'use strict';
  var K_DONE = 'vx_setup_done', K_INSTALL = 'vx_install_dismissed';
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  function geoState() {
    if (!navigator.permissions || !navigator.permissions.query) return Promise.resolve('unknown');
    return navigator.permissions.query({name: 'geolocation'}).then(function (p) { return p.state; }, function () { return 'unknown'; });
  }
  function isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  }
  function isIOS() { return /iphone|ipad|ipod/i.test(navigator.userAgent); }

  // --- service worker ---
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () { navigator.serviceWorker.register('/sw.js').catch(function () {}); });
  }

  // --- install as app ---
  var deferredInstall = null;
  window.addEventListener('beforeinstallprompt', function (e) { e.preventDefault(); deferredInstall = e; document.dispatchEvent(new Event('vx:installable')); });
  window.addEventListener('appinstalled', function () { deferredInstall = null; set(K_INSTALL, '1'); });

  function requestGeo() {
    return new Promise(function (resolve) {
      if (!navigator.geolocation) return resolve('unsupported');
      navigator.geolocation.getCurrentPosition(function () { resolve('granted'); },
        function (err) { resolve(err && err.code === 1 ? 'denied' : 'granted-no-fix'); },
        {enableHighAccuracy: true, timeout: 20000, maximumAge: 60000});
    });
  }

  window.VXPerm = {
    geoState: geoState, isStandalone: isStandalone, isIOS: isIOS, requestGeo: requestGeo,
    setupDone: function () { return get(K_DONE) === '1'; },
    markDone: function () { set(K_DONE, '1'); },
    canInstall: function () { return !!deferredInstall; },
    install: function () {
      if (!deferredInstall) return Promise.resolve(false);
      deferredInstall.prompt();
      return deferredInstall.userChoice.then(function (c) { deferredInstall = null; set(K_INSTALL, '1'); return c.outcome === 'accepted'; });
    },
    installDismissed: function () { return get(K_INSTALL) === '1'; },
    dismissInstall: function () { set(K_INSTALL, '1'); }
  };
})();
