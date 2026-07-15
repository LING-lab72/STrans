const slides = [...document.querySelectorAll('.slide')];
const progress = document.querySelector('#deck-progress');
let activeIndex = 0;

function showSlide(index) {
  activeIndex = Math.max(0, Math.min(index, slides.length - 1));
  slides[activeIndex].scrollIntoView({ behavior: 'smooth', block: 'center' });
  progress.textContent = `${activeIndex + 1} / ${slides.length}`;
  history.replaceState(null, '', `#slide-${activeIndex + 1}`);
}

document.querySelector('#prev-slide').addEventListener('click', () => showSlide(activeIndex - 1));
document.querySelector('#next-slide').addEventListener('click', () => showSlide(activeIndex + 1));
document.querySelector('#print-deck').addEventListener('click', () => window.print());

document.addEventListener('keydown', (event) => {
  if (['ArrowRight', 'PageDown', ' '].includes(event.key)) {
    event.preventDefault();
    showSlide(activeIndex + 1);
  }
  if (['ArrowLeft', 'PageUp'].includes(event.key)) {
    event.preventDefault();
    showSlide(activeIndex - 1);
  }
  if (event.key === 'Home') showSlide(0);
  if (event.key === 'End') showSlide(slides.length - 1);
});

const initial = Number(location.hash.replace('#slide-', '')) - 1;
if (Number.isInteger(initial) && initial >= 0) activeIndex = Math.min(initial, slides.length - 1);
progress.textContent = `${activeIndex + 1} / ${slides.length}`;
