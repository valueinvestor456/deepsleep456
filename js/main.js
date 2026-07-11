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
  function ensureSlideBg(slide) {
    var bg = slide.getAttribute("data-bg");
    if (bg && !slide.style.backgroundImage) slide.style.backgroundImage = "url('" + bg + "')";
  }
  if (slides.length > 1) {
    var current = 0;
    // Warm only the second slide shortly before the first rotation; every
    // later slide is warmed one rotation ahead. Loading all of them at once
    // used to pull ~550KB during page load and wreck LCP on slow networks.
    setTimeout(function () { ensureSlideBg(slides[1]); }, 4000);
    setInterval(function () {
      var next = (current + 1) % slides.length;
      ensureSlideBg(slides[next]);
      slides[current].classList.remove("hero__slide--active");
      slides[next].classList.add("hero__slide--active");
      current = next;
      ensureSlideBg(slides[(next + 1) % slides.length]);
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

  // Amenity photo preview: hover (desktop) or tap (touch) reveals a supporting
  // photo. The image is only fetched on first interaction, not on page load.
  var amenityCards = document.querySelectorAll("[data-photo]");
  var activeAmenity = null;

  function loadAmenityPhoto(card) {
    var img = card.querySelector(".amenity__preview img");
    if (img && !img.getAttribute("src")) {
      img.setAttribute("src", card.getAttribute("data-photo"));
      img.setAttribute("alt", card.getAttribute("data-photo-alt") || "");
    }
  }

  function closeAmenity(card) {
    card.classList.remove("is-active");
    if (activeAmenity === card) activeAmenity = null;
  }

  amenityCards.forEach(function (card) {
    card.addEventListener("mouseenter", function () { loadAmenityPhoto(card); });
    card.addEventListener("focus", function () { loadAmenityPhoto(card); });
    card.addEventListener("click", function () {
      loadAmenityPhoto(card);
      var willOpen = !card.classList.contains("is-active");
      if (activeAmenity && activeAmenity !== card) closeAmenity(activeAmenity);
      card.classList.toggle("is-active", willOpen);
      activeAmenity = willOpen ? card : null;
    });
  });
  document.addEventListener("click", function (e) {
    if (activeAmenity && !activeAmenity.contains(e.target)) closeAmenity(activeAmenity);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && activeAmenity) closeAmenity(activeAmenity);
  });

  // Live temperature badge in the climate section (Open-Meteo, no API key,
  // modeled for the property's exact coordinates rather than the district).
  var climateLive = document.querySelector("[data-climate-live]");
  if (climateLive) {
    var lang = document.documentElement.lang === "en" ? "en" : "th";
    var weatherLabels = {
      th: { 0: "ท้องฟ้าแจ่มใส", 1: "มีเมฆบางส่วน", 2: "มีเมฆบางส่วน", 3: "เมฆมาก", 45: "หมอก", 48: "หมอก",
        51: "ฝนตกปรอยๆ", 53: "ฝนตกปรอยๆ", 55: "ฝนตกปรอยๆ", 61: "ฝนตกเล็กน้อย", 63: "ฝนตกปานกลาง", 65: "ฝนตกหนัก",
        80: "ฝนตกเป็นช่วง", 81: "ฝนตกเป็นช่วง", 82: "ฝนตกหนักเป็นช่วง", 95: "พายุฝนฟ้าคะนอง" },
      en: { 0: "Clear sky", 1: "Partly cloudy", 2: "Partly cloudy", 3: "Overcast", 45: "Foggy", 48: "Foggy",
        51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
        80: "Rain showers", 81: "Rain showers", 82: "Heavy showers", 95: "Thunderstorm" }
    };
    var textEl = climateLive.querySelector(".climate-live__text");
    fetch("https://api.open-meteo.com/v1/forecast?latitude=18.8922564&longitude=98.8279099&current=temperature_2m,weather_code&timezone=Asia%2FBangkok")
      .then(function (res) { if (!res.ok) throw new Error("bad response"); return res.json(); })
      .then(function (data) {
        var c = data.current;
        var label = weatherLabels[lang][c.weather_code] || (lang === "th" ? "มีเมฆ" : "Cloudy");
        var time = new Date(c.time).toLocaleTimeString(lang === "th" ? "th-TH" : "en-US", { hour: "2-digit", minute: "2-digit" });
        textEl.textContent = lang === "th"
          ? "อุณหภูมิตอนนี้ที่โป่งแยง: " + c.temperature_2m.toFixed(1) + "°C · " + label + " · อัปเดต " + time + " น."
          : "Right now in Pong Yaeng: " + c.temperature_2m.toFixed(1) + "°C · " + label + " · updated " + time;
        climateLive.classList.remove("climate-live--loading");
      })
      .catch(function () {
        climateLive.classList.add("climate-live--error");
      });
  }

  // Review video: the YouTube player is only loaded after the visitor taps
  // play, so the heavy embed script never affects initial page load.
  var videoFacades = document.querySelectorAll(".video-facade[data-video-id]");
  for (var v = 0; v < videoFacades.length; v++) {
    videoFacades[v].addEventListener("click", function () {
      var id = this.getAttribute("data-video-id");
      var iframe = document.createElement("iframe");
      iframe.src = "https://www.youtube-nocookie.com/embed/" + id + "?autoplay=1&playsinline=1";
      iframe.title = this.getAttribute("aria-label") || "YouTube video";
      iframe.setAttribute("allow", "autoplay; encrypted-media; picture-in-picture");
      iframe.setAttribute("allowfullscreen", "");
      this.innerHTML = "";
      this.appendChild(iframe);
      this.style.cursor = "default";
    }, { once: true });
  }

  // Influencer / affiliate referral tracking. A partner shares a link like
  // ?ref=NEWVI; we remember the code for the session, show a banner, and
  // rewrite LINE links to a pre-filled chat message so the code travels with
  // the booking request without the guest needing to type it themselves.
  // To onboard a new partner, just add a row to REF_PARTNERS below.
  var REF_PARTNERS = {
    NEWVI: { th: "เชียงใหม่ม่วนเว่อร์", en: "Chiang Mai Muan Ver" }
  };
  var refBanner = document.querySelector("[data-ref-banner]");
  if (refBanner) {
    var urlRef = new URLSearchParams(location.search).get("ref");
    if (urlRef) {
      try { sessionStorage.setItem("ds456_ref", urlRef.toUpperCase()); } catch (e) {}
    }
    var activeRef = null;
    try { activeRef = sessionStorage.getItem("ds456_ref"); } catch (e) {}
    var partner = activeRef && REF_PARTNERS[activeRef];
    if (partner) {
      var refLang = document.documentElement.lang === "en" ? "en" : "th";
      var partnerName = partner[refLang];
      var bannerText = refBanner.querySelector("[data-ref-banner-text]");
      if (bannerText) {
        bannerText.innerHTML = refLang === "th"
          ? "🎉 คุณมาจาก " + partnerName + " — แจ้งโค้ด <strong>" + activeRef + "</strong> ตอนจองผ่าน LINE หรือโทร รับสิทธิพิเศษ"
          : "🎉 Referred by " + partnerName + " — mention code <strong>" + activeRef + "</strong> when you book via LINE or phone";
      }
      refBanner.hidden = false;
      refBanner.classList.add("is-visible");

      var lineMsg = refLang === "th"
        ? "สวัสดีค่ะ สนใจจองที่พัก Deepsleep456 (รหัสแนะนำ: " + activeRef + ")"
        : "Hi! I'm interested in booking Deepsleep456 (referral code: " + activeRef + ")";
      var lineLinks = document.querySelectorAll('a[href^="https://line.me/R/ti/p/"]');
      for (var l = 0; l < lineLinks.length; l++) {
        lineLinks[l].href = "https://line.me/R/oaMessage/@952gwewf/?" + encodeURIComponent(lineMsg);
      }
    }
  }
})();
