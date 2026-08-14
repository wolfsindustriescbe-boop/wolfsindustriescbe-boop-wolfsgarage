document.addEventListener("DOMContentLoaded", () => {
    const slider = document.querySelector(".hero-slider");

    if (!slider) {
        return;
    }

    const slides = Array.from(slider.querySelectorAll(".slide"));
    const dots = Array.from(slider.querySelectorAll(".dot"));
    const prevButton = slider.querySelector(".prev");
    const nextButton = slider.querySelector(".next");

    if (slides.length === 0) {
        return;
    }

    let currentIndex = Math.max(
        slides.findIndex((slide) => slide.classList.contains("active")),
        0
    );

    const showSlide = (index) => {
        const normalizedIndex = (index + slides.length) % slides.length;
        currentIndex = normalizedIndex;

        slides.forEach((slide, slideIndex) => {
            slide.classList.toggle("active", slideIndex === normalizedIndex);
        });

        dots.forEach((dot, dotIndex) => {
            dot.classList.toggle("active", dotIndex === normalizedIndex);
        });
    };

    prevButton?.addEventListener("click", () => {
        showSlide(currentIndex - 1);
    });

    nextButton?.addEventListener("click", () => {
        showSlide(currentIndex + 1);
    });

    dots.forEach((dot, index) => {
        dot.addEventListener("click", () => showSlide(index));
    });

    setInterval(() => {
        showSlide(currentIndex + 1);
    }, 6000);
});
