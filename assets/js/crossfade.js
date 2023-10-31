let crossfade = (function () {
    let crossfadeImage = async function(){
        console.log('Getting crossfaded...')
        let current = document.querySelector('.crossfade img.current') || document.querySelector('.crossfade img:first-child'),
            next = current.nextElementSibling || document.querySelector('.crossfade img:first-child');

        console.log('Current: ', current);
        console.log('Next: ', next);

        current.classList.remove('current');
        next.classList.add('current');
    }

    setInterval(crossfadeImage, 6900);
})();
