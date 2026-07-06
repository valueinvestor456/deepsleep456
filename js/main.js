(function () {
  "use strict";

  // Footer year
  var yearEl = document.querySelector("[data-year]");
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  // Mobile nav toggle
  var menuToggle = document.querySelector("[data-menu-toggle]");
  var menu = document.querySelector("[data-menu]");
  if (menuToggle && menu) {
    menuToggle.addEventListener("click", function () {
      var open = menu.getAttribute("data-open") === "true";
      menu.setAttribute("data-open", String(!open));
      menuToggle.setAttribute("aria-expanded", String(!open));
    });
    menu.querySelectorAll(".nav__link").forEach(function (link) {
      link.addEventListener("click", function () {
        menu.setAttribute("data-open", "false");
        menuToggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  // Hero slider (auto-cycle background slides)
  // Slides after the first carry their image in data-bg instead of an inline
  // background so the browser doesn't fetch them eagerly and compete with
  // the LCP image; they're swapped in only after the page has settled.
  var slides = document.querySelectorAll("[data-hero-slider] .hero__slide");
  window.addEventListener("load", function () {
    slides.forEach(function (slide) {
      var bg = slide.getAttribute("data-bg");
      if (bg) slide.style.backgroundImage = "url('" + bg + "')";
    });
  });
  if (slides.length > 1) {
    var current = 0;
    setInterval(function () {
      slides[current].classList.remove("hero__slide--active");
      current = (current + 1) % slides.length;
      slides[current].classList.add("hero__slide--active");
    }, 5500);
  }

  // Gallery filter
  var filterButtons = document.querySelectorAll(".gallery__filter");
  var galleryItems = document.querySelectorAll(".gallery__item");
  filterButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      filterButtons.forEach(function (b) { b.classList.remove("gallery__filter--active"); });
      btn.classList.add("gallery__filter--active");
      var filter = btn.getAttribute("data-filter");
      galleryItems.forEach(function (item) {
        var show = filter === "all" || item.getAttribute("data-category") === filter;
        item.classList.toggle("gallery__item--hidden", !show);
      });
    });
  });

  // Lightbox
  var lightbox = document.querySelector("[data-lightbox-modal]");
  var lightboxImg = lightbox ? lightbox.querySelector(".lightbox__image") : null;
  var closeBtn = document.querySelector("[data-lightbox-close]");
  var prevBtn = document.querySelector("[data-lightbox-prev]");
  var nextBtn = document.querySelector("[data-lightbox-next]");
  var galleryList = Array.prototype.slice.call(galleryItems);
  var activeIndex = -1;

  function visibleItems() {
    return galleryList.filter(function (item) { return !item.classList.contains("gallery__item--hidden"); });
  }

  function openLightbox(item) {
    var items = visibleItems();
    activeIndex = items.indexOf(item);
    showActive(items);
    lightbox.setAttribute("data-open", "true");
    lightbox.setAttribute("aria-hidden", "false");
  }

  function showActive(items) {
    if (!items.length) return;
    var item = items[activeIndex];
    var src = item.getAttribute("data-lightbox");
    var alt = item.querySelector("img").getAttribute("alt");
    lightboxImg.setAttribute("src", src);
    lightboxImg.setAttribute("alt", alt);
  }

  function closeLightbox() {
    lightbox.setAttribute("data-open", "false");
    lightbox.setAttribute("aria-hidden", "true");
    lightboxImg.setAttribute("src", "");
  }

  galleryItems.forEach(function (item) {
    item.addEventListener("click", function () { openLightbox(item); });
  });
  if (closeBtn) closeBtn.addEventListener("click", closeLightbox);
  if (lightbox) {
    lightbox.addEventListener("click", function (e) {
      if (e.target === lightbox) closeLightbox();
    });
  }
  if (prevBtn) prevBtn.addEventListener("click", function () {
    var items = visibleItems();
    if (!items.length) return;
    activeIndex = (activeIndex - 1 + items.length) % items.length;
    showActive(items);
  });
  if (nextBtn) nextBtn.addEventListener("click", function () {
    var items = visibleItems();
    if (!items.length) return;
    activeIndex = (activeIndex + 1) % items.length;
    showActive(items);
  });
  document.addEventListener("keydown", function (e) {
    if (lightbox && lightbox.getAttribute("data-open") === "true") {
      if (e.key === "Escape") closeLightbox();
      if (e.key === "ArrowLeft" && prevBtn) prevBtn.click();
      if (e.key === "ArrowRight" && nextBtn) nextBtn.click();
    }
  });
})();
