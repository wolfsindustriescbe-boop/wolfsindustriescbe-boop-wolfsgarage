document.addEventListener("DOMContentLoaded", () => {
    const body = document.body;
    const navToggle = document.querySelector("[data-admin-nav-toggle]");
    const mobileNavLinks = document.querySelectorAll("[data-admin-mobile-link]");
    const previewInputs = document.querySelectorAll("[data-preview-input]");
    const dateTargets = document.querySelectorAll("[data-current-date]");

    const closeNav = () => {
        body.classList.remove("admin-nav-open");
        navToggle?.setAttribute("aria-expanded", "false");
    };

    const openNav = () => {
        body.classList.add("admin-nav-open");
        navToggle?.setAttribute("aria-expanded", "true");
    };

    navToggle?.addEventListener("click", () => {
        if (body.classList.contains("admin-nav-open")) {
            closeNav();
        } else {
            openNav();
        }
    });

    mobileNavLinks.forEach((link) => {
        link.addEventListener("click", closeNav);
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeNav();
        }
    });

    document.addEventListener("click", (event) => {
        if (!body.classList.contains("admin-nav-open")) {
            return;
        }

        const mobileNav = document.querySelector(".admin-mobile-nav");
        const clickedInsideNav = mobileNav?.contains(event.target);
        const clickedToggle = navToggle?.contains(event.target);

        if (!clickedInsideNav && !clickedToggle) {
            closeNav();
        }
    });

    dateTargets.forEach((target) => {
        const formatter = new Intl.DateTimeFormat("en-IN", {
            weekday: "long",
            year: "numeric",
            month: "long",
            day: "numeric",
        });
        target.textContent = formatter.format(new Date());
    });

    previewInputs.forEach((input) => {
        const targetSelector = input.getAttribute("data-preview-target");
        if (!targetSelector) {
            return;
        }

        const target = document.querySelector(targetSelector);
        if (!target) {
            return;
        }

        const renderPreview = (file) => {
            if (!file) {
                target.innerHTML = '<div class="muted">No image selected yet.</div>';
                return;
            }

            const reader = new FileReader();
            reader.onload = (event) => {
                target.innerHTML = `<img src="${event.target.result}" alt="Preview">`;
            };
            reader.readAsDataURL(file);
        };

        input.addEventListener("change", (event) => {
            const file = event.target.files && event.target.files[0];
            renderPreview(file);
        });
    });
});

