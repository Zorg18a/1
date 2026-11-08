// Работает только на время загрузки манги и только когда окно скрыто: в скрытом окне браузер не отдаёт странице события видимости,
// поэтому ленивые картинки не грузятся. Здесь сообщаем странице, что каждый наблюдаемый элемент виден.
(() => {
  const Orig = window.IntersectionObserver; if (!Orig || Orig.__mh) return;
  class IO extends Orig {
    constructor(cb, opt) { super(cb, opt); this._mh = cb; }
    observe(el) {
      super.observe(el);
      if (document.visibilityState === 'hidden') { try { const r = el.getBoundingClientRect(); this._mh([{ target: el, isIntersecting: true, intersectionRatio: 1, boundingClientRect: r, intersectionRect: r, rootBounds: null, time: performance.now() }], this); } catch (e) {} }
    }
  }
  IO.__mh = true; window.IntersectionObserver = IO;
})();
