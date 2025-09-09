
document.addEventListener('DOMContentLoaded', function () {
    const cards = document.querySelectorAll('.platform-card');
    const platformInput = document.getElementById('platformInput');
    const form = document.getElementById('searchForm');

    if (!cards.length || !platformInput || !form) {
        console.warn("Some DOM elements are missing. Check that your HTML has the correct IDs and classes.");
        return;
    }

    cards.forEach(card => {
        card.addEventListener('click', () => {
            // Clear previous active selections
            cards.forEach(c => c.classList.remove('selected-platform'));

            // Mark clicked card
            card.classList.add('selected-platform');

            // Set hidden platform value
            const platform = card.getAttribute('data-platform');
            platformInput.value = platform;

            // Optional: Auto-submit form
            form.submit();
        });
    });
});
