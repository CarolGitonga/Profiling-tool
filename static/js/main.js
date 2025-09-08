document.addEventListener('DOMContentLoaded', function () {
    const platformCards = document.querySelectorAll('.card-platform');

    platformCards.forEach(card => {
        card.addEventListener('click', () => {
            const platform = card.dataset.platform;
            document.querySelector('#id_platform').value = platform;
            document.querySelector('#platformForm').submit();
        });
    });
});
