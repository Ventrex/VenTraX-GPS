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

  // Safari asks again on every page load unless the site is set to "Allow" in its website settings.
  // A web page cannot change that setting, so we show the (30 second) fix instead.
  function iosTipHtml() {
    return '<b>Safari blijft om toestemming vragen?</b> Zet het één keer vast: tik op <b>aA</b> in de adresbalk → ' +
           '<b>Websiteinstellingen</b> → zet <b>Locatie</b>, <b>Camera</b> en <b>Microfoon</b> op <b>Toestaan</b>. ' +
           'Daarna vraagt Safari het niet meer. Nog beter: <b>Deel</b> <i class="fas fa-arrow-up-from-bracket"></i> → ' +
           '<b>Zet op beginscherm</b> en open VenTrax als app.';
  }
  function showIosTip(el) {
    if (!el || !isIOS() || isStandalone() || get('vx_ios_tip_done') === '1') return;
    el.innerHTML = '<i class="fas fa-circle-info"></i><span>' + iosTipHtml() +
      ' <a href="#" style="text-decoration:underline" onclick="VXPerm.hideIosTip(this);return false">Gedaan, niet meer tonen</a></span>';
    el.style.display = 'flex';
  }

  window.VXPerm = {
    iosTipHtml: iosTipHtml, showIosTip: showIosTip,
    hideIosTip: function (a) { set('vx_ios_tip_done', '1'); var box = a.closest('.alert'); if (box) box.style.display = 'none'; },
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
