/**
 * Conserva scroll al filtrar/paginar.
 * Soft-nav de sub-secciones (Eventos) sin recargar header.
 * Opción 4: underline animado, tabla/contenido instantáneo.
 */
(function () {
    'use strict';

    var pathKey = 'lv:' + location.pathname;
    var SCROLL_KEY = pathKey + ':scroll';
    var softBusy = false;

    function remember() {
        try {
            sessionStorage.setItem(SCROLL_KEY, String(window.scrollY || window.pageYOffset || 0));
        } catch (e) { /* private mode */ }
    }

    function samePath(href) {
        try {
            var url = new URL(href, location.href);
            return url.origin === location.origin && url.pathname === location.pathname;
        } catch (e) {
            return false;
        }
    }

    function shouldTrackAnchor(a) {
        if (!a || !a.getAttribute) return false;
        var href = a.getAttribute('href');
        if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0) return false;
        if (a.target && a.target !== '_self') return false;
        if (a.hasAttribute('download')) return false;
        if (a.closest('[data-lv-ignore]')) return false;
        return samePath(a.href);
    }

    document.addEventListener('click', function (e) {
        if (e.defaultPrevented) return;
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        var a = e.target.closest && e.target.closest('a[href]');
        if (shouldTrackAnchor(a)) remember();
    }, true);

    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form || form.tagName !== 'FORM') return;
        if (form.closest('[data-lv-ignore]')) return;
        var method = (form.getAttribute('method') || 'get').toLowerCase();
        if (method !== 'get') return;
        var action = form.getAttribute('action') || location.href;
        if (samePath(action)) remember();
    }, true);

    function restoreScroll() {
        var raw;
        try {
            raw = sessionStorage.getItem(SCROLL_KEY);
            if (raw === null) return;
            sessionStorage.removeItem(SCROLL_KEY);
        } catch (e) {
            return;
        }
        var top = parseInt(raw, 10) || 0;
        var apply = function () { window.scrollTo(0, top); };
        apply();
        requestAnimationFrame(function () {
            apply();
            requestAnimationFrame(apply);
        });
        window.addEventListener('load', apply, { once: true });
        setTimeout(apply, 50);
        setTimeout(apply, 200);
        window.addEventListener('pageshow', apply, { once: true });
    }

    window.moveTabsInk = function (bar, activeTab, animate) {
        if (!bar || !activeTab) return;
        var ink = bar.querySelector('.tabs-ink');
        if (!ink) return;
        var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        ink.style.transition = (!animate || reduce) ? 'none' : '';
        var barRect = bar.getBoundingClientRect();
        var tabRect = activeTab.getBoundingClientRect();
        ink.style.width = Math.round(tabRect.width) + 'px';
        ink.style.transform = 'translateX(' + Math.round(tabRect.left - barRect.left + bar.scrollLeft) + 'px)';
    };

    function ensureStyleSlot() {
        var slot = document.getElementById('soft-page-styles');
        if (!slot) {
            slot = document.createElement('div');
            slot.id = 'soft-page-styles';
            document.head.appendChild(slot);
        }
        return slot;
    }

    function applyDocStyles(doc) {
        var slot = ensureStyleSlot();
        slot.innerHTML = '';
        doc.querySelectorAll('head style').forEach(function (st) {
            slot.appendChild(document.importNode(st, true));
        });
    }

    function rehydrateScripts(root) {
        root.querySelectorAll('script').forEach(function (old) {
            var s = document.createElement('script');
            Array.prototype.forEach.call(old.attributes, function (attr) {
                s.setAttribute(attr.name, attr.value);
            });
            if (!old.src) s.textContent = old.textContent;
            old.parentNode.replaceChild(s, old);
        });
    }

    /**
     * Soft-nav: mantiene header, reemplaza #*-soft-root, anima ink.
     */
    function loadHeadAssets(doc) {
        return new Promise(function (resolve) {
            var pending = 0;
            function done() {
                pending -= 1;
                if (pending <= 0) resolve();
            }
            doc.querySelectorAll('head link[rel="stylesheet"]').forEach(function (link) {
                var href = link.getAttribute('href');
                if (!href) return;
                if (document.querySelector('link[href="' + href + '"]')) return;
                pending += 1;
                var l = document.createElement('link');
                l.rel = 'stylesheet';
                l.href = href;
                l.onload = done;
                l.onerror = done;
                document.head.appendChild(l);
            });
            doc.querySelectorAll('head script[src]').forEach(function (scr) {
                var src = scr.getAttribute('src');
                if (!src) return;
                if (document.querySelector('script[src="' + src + '"]')) return;
                pending += 1;
                var s = document.createElement('script');
                s.src = src;
                s.onload = done;
                s.onerror = done;
                document.head.appendChild(s);
            });
            if (pending === 0) resolve();
        });
    }

    window.softPageNav = async function (url, opts) {
        opts = opts || {};
        if (softBusy) return;
        softBusy = true;
        var rootId = opts.rootId || 'hallazgos-soft-root';
        try {
            var res = await fetch(url, {
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            var html = await res.text();
            var doc = new DOMParser().parseFromString(html, 'text/html');
            var next = doc.getElementById(rootId);
            var cur = document.getElementById(rootId);
            if (!next || !cur) {
                window.location.href = url;
                return;
            }

            await loadHeadAssets(doc);
            applyDocStyles(doc);
            var imported = document.importNode(next, true);
            cur.replaceWith(imported);
            rehydrateScripts(document.getElementById(rootId));

            document.title = doc.title || document.title;
            if (opts.push !== false) history.pushState({ softPage: true, rootId: rootId }, '', url);
            window.scrollTo(0, 0);

            var barId = opts.barId;
            if (barId) {
                var bar = document.getElementById(barId);
                if (bar) {
                    bar.removeAttribute('data-ink-bound');
                    window.bindTabsInkNav(barId, {
                        softRootId: rootId,
                        soft: true
                    });
                }
            }
        } catch (err) {
            window.location.href = url;
        } finally {
            softBusy = false;
        }
    };

    window.bindTabsInkNav = function (barId, opts) {
        opts = opts || {};
        var bar = document.getElementById(barId);
        if (!bar || bar.getAttribute('data-ink-bound') === '1') return;
        bar.setAttribute('data-ink-bound', '1');

        function place(animate) {
            var active = bar.querySelector('a.active');
            window.moveTabsInk(bar, active, !!animate);
        }

        place(false);
        requestAnimationFrame(function () { place(false); });

        bar.addEventListener('click', function (e) {
            var link = e.target.closest && e.target.closest('a[href]');
            if (!link || !bar.contains(link)) return;
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
            if (link.classList.contains('active')) return;

            e.preventDefault();
            e.stopPropagation();

            bar.querySelectorAll('a').forEach(function (a) { a.classList.remove('active'); });
            link.classList.add('active');
            window.moveTabsInk(bar, link, true);

            var href = link.href;
            var useSoft = opts.soft && document.getElementById(opts.softRootId || 'hallazgos-soft-root');

            if (useSoft) {
                window.softPageNav(href, {
                    rootId: opts.softRootId || 'hallazgos-soft-root',
                    barId: barId,
                    push: true
                });
                return;
            }

            var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            setTimeout(function () {
                window.location.href = href;
            }, reduce ? 0 : 180);
        }, true);

        window.addEventListener('resize', function () { place(false); });
    };

    function autoBindInkNavs() {
        if (document.getElementById('hallazgos-soft-root') && document.getElementById('hallazgos-sub-nav')) {
            window.bindTabsInkNav('hallazgos-sub-nav', {
                soft: true,
                softRootId: 'hallazgos-soft-root'
            });
        } else if (document.getElementById('hallazgos-sub-nav')) {
            window.bindTabsInkNav('hallazgos-sub-nav');
        }

        if (document.getElementById('eventos-soft-root') && document.getElementById('eventos-sub-nav')) {
            window.bindTabsInkNav('eventos-sub-nav', {
                soft: true,
                softRootId: 'eventos-soft-root'
            });
        } else if (document.getElementById('eventos-sub-nav')) {
            window.bindTabsInkNav('eventos-sub-nav');
        }

        ['licencias-tabs', 'equipos-tabs'].forEach(function (id) {
            var el = document.getElementById(id);
            if (!el) return;
            var active = el.querySelector('a.active');
            window.moveTabsInk(el, active, false);
        });
    }

    window.addEventListener('popstate', function (e) {
        if (!e.state || !e.state.softPage) return;
        var rootId = e.state.rootId || 'hallazgos-soft-root';
        if (!document.getElementById(rootId)) return;
        window.softPageNav(location.href, {
            rootId: rootId,
            barId: rootId.indexOf('eventos') === 0 ? 'eventos-sub-nav' : 'hallazgos-sub-nav',
            push: false
        });
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', autoBindInkNavs);
    } else {
        autoBindInkNavs();
    }

    restoreScroll();
})();
