// Landing hero: two slowly turning spiral galaxies, twinkling stars, rockets crossing
// now and then, and a trail of stars left by the pointer. Static when the user prefers
// reduced motion; paused while the hero is off screen or the tab is hidden.
(function () {
    const canvas = document.getElementById('galaxy');
    if (!canvas) return;
    const hero = canvas.parentElement;
    const ctx = canvas.getContext('2d');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const TILT = -0.4;

    let width = 0, height = 0;
    let stars = [], galaxies = [], rockets = [], trail = [];
    let visible = true, frameRequested = false, last = performance.now(), nextRocket = 1200;

    function spiral(count) {
        const arms = 3, points = [];
        for (let i = 0; i < count; i++) {
            const distance = Math.pow(Math.random(), 0.7);  // denser towards the core
            const arm = (i % arms) * (Math.PI * 2 / arms);
            points.push({
                distance,
                angle: arm + distance * 5 + (Math.random() - 0.5) * 0.7,
                size: Math.random() * 1.2 + 0.3,
                light: 60 + Math.random() * 30,
            });
        }
        return points;
    }

    function resize() {
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        width = hero.clientWidth;
        height = hero.clientHeight;
        canvas.width = width * ratio;
        canvas.height = height * ratio;
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        stars = Array.from({ length: Math.round(width * height / 2600) }, () => ({
            x: Math.random() * width,
            y: Math.random() * height,
            size: Math.random() * 1.2 + 0.2,
            alpha: Math.random() * 0.6 + 0.25,
            phase: Math.random() * Math.PI * 2,
            twinkle: Math.random() * 0.002 + 0.0005,
            drift: Math.random() * 0.004 + 0.001,
        }));
        const base = Math.min(width, height);
        galaxies = [
            { x: width * 0.8, y: height * 0.28, size: base * 0.34, tilt: 0.42, angle: 0, speed: 0.00005, hue: 215, points: spiral(1000) },
            { x: width * 0.1, y: height * 0.82, size: base * 0.2, tilt: 0.6, angle: 1.2, speed: -0.00008, hue: 262, points: spiral(500) },
        ];
    }

    function drawGalaxy(galaxy, dt) {
        galaxy.angle += galaxy.speed * dt;
        const core = ctx.createRadialGradient(galaxy.x, galaxy.y, 0, galaxy.x, galaxy.y, galaxy.size * 0.55);
        core.addColorStop(0, `hsla(${galaxy.hue}, 90%, 88%, 0.4)`);
        core.addColorStop(0.25, `hsla(${galaxy.hue}, 80%, 60%, 0.14)`);
        core.addColorStop(1, 'hsla(0, 0%, 0%, 0)');
        ctx.fillStyle = core;
        ctx.beginPath();
        ctx.ellipse(galaxy.x, galaxy.y, galaxy.size * 0.55, galaxy.size * 0.55 * galaxy.tilt, TILT, 0, Math.PI * 2);
        ctx.fill();
        const cos = Math.cos(TILT), sin = Math.sin(TILT);
        for (const point of galaxy.points) {
            const angle = point.angle + galaxy.angle;
            const radius = point.distance * galaxy.size;
            const px = Math.cos(angle) * radius;
            const py = Math.sin(angle) * radius * galaxy.tilt;
            ctx.fillStyle = `hsla(${galaxy.hue + point.distance * 40}, 85%, ${point.light}%, ${0.8 - point.distance * 0.55})`;
            ctx.fillRect(galaxy.x + px * cos - py * sin, galaxy.y + px * sin + py * cos, point.size, point.size);
        }
    }

    function drawStars(dt) {
        for (const star of stars) {
            star.phase += star.twinkle * dt;
            star.x -= star.drift * dt;
            if (star.x < 0) star.x += width;
            ctx.globalAlpha = star.alpha * (0.55 + 0.45 * Math.sin(star.phase));
            ctx.fillStyle = '#fff';
            ctx.fillRect(star.x, star.y, star.size, star.size);
        }
        ctx.globalAlpha = 1;
    }

    function launchRocket() {
        const fromLeft = Math.random() < 0.5;
        const startY = height * (0.35 + Math.random() * 0.6);
        const endY = startY - height * (0.3 + Math.random() * 0.5);
        const startX = fromLeft ? -40 : width + 40;
        const endX = fromLeft ? width + 40 : -40;
        const angle = Math.atan2(endY - startY, endX - startX);
        const speed = 0.16 + Math.random() * 0.1;  // px per ms
        rockets.push({ x: startX, y: startY, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed, angle, size: 9 + Math.random() * 6, puffs: [] });
    }

    function drawRocket(rocket, dt) {
        rocket.x += rocket.vx * dt;
        rocket.y += rocket.vy * dt;
        const s = rocket.size;
        rocket.puffs.push({ x: rocket.x - Math.cos(rocket.angle) * s, y: rocket.y - Math.sin(rocket.angle) * s, life: 1 });
        for (const puff of rocket.puffs) puff.life -= dt / 800;
        rocket.puffs = rocket.puffs.filter(puff => puff.life > 0);
        for (const puff of rocket.puffs) {
            ctx.fillStyle = `rgba(255, ${Math.round(140 + puff.life * 100)}, 90, ${puff.life * 0.45})`;
            ctx.beginPath();
            ctx.arc(puff.x, puff.y, (1 - puff.life) * 7 + 1, 0, Math.PI * 2);
            ctx.fill();
        }

        ctx.save();
        ctx.translate(rocket.x, rocket.y);
        ctx.rotate(rocket.angle);
        // Flame
        ctx.fillStyle = 'rgba(255, 176, 64, 0.95)';
        ctx.beginPath();
        ctx.moveTo(-s * 0.7, -s * 0.18);
        ctx.lineTo(-s * (1.2 + Math.random() * 0.5), 0);
        ctx.lineTo(-s * 0.7, s * 0.18);
        ctx.fill();
        // Fins
        ctx.fillStyle = '#3b82f6';
        for (const side of [-1, 1]) {
            ctx.beginPath();
            ctx.moveTo(-s * 0.3, side * s * 0.28);
            ctx.lineTo(-s * 0.8, side * s * 0.62);
            ctx.lineTo(-s * 0.72, side * s * 0.22);
            ctx.fill();
        }
        // Body and window
        ctx.fillStyle = '#e2e8f0';
        ctx.beginPath();
        ctx.moveTo(s, 0);
        ctx.quadraticCurveTo(s * 0.35, -s * 0.4, -s * 0.72, -s * 0.28);
        ctx.lineTo(-s * 0.72, s * 0.28);
        ctx.quadraticCurveTo(s * 0.35, s * 0.4, s, 0);
        ctx.fill();
        ctx.fillStyle = '#60a5fa';
        ctx.beginPath();
        ctx.arc(s * 0.22, 0, s * 0.13, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        return rocket.x > -80 && rocket.x < width + 80 && rocket.y > -80 && rocket.y < height + 80;
    }

    function sparkle(x, y, size, alpha, hue, rotation) {
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(rotation);
        ctx.fillStyle = `hsla(${hue}, 100%, 90%, ${alpha * 0.25})`;
        ctx.beginPath();
        ctx.arc(0, 0, size * 1.6, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = `hsla(${hue}, 100%, 88%, ${alpha})`;
        ctx.beginPath();
        ctx.moveTo(0, -size);
        ctx.quadraticCurveTo(0, 0, size, 0);
        ctx.quadraticCurveTo(0, 0, 0, size);
        ctx.quadraticCurveTo(0, 0, -size, 0);
        ctx.quadraticCurveTo(0, 0, 0, -size);
        ctx.fill();
        ctx.restore();
    }

    function drawTrail(dt) {
        for (const star of trail) {
            star.life -= dt / 2600;
            star.x += star.vx * dt;
            star.y += star.vy * dt;
            star.rotation += dt * 0.002;
        }
        trail = trail.filter(star => star.life > 0);
        for (const star of trail) sparkle(star.x, star.y, star.size * (0.4 + star.life * 0.6), star.life, star.hue, star.rotation);
    }

    function draw(now) {
        frameRequested = false;
        const dt = Math.min(now - last, 50);
        last = now;
        ctx.clearRect(0, 0, width, height);
        for (const galaxy of galaxies) drawGalaxy(galaxy, dt);
        drawStars(dt);
        nextRocket -= dt;
        if (nextRocket <= 0) {
            launchRocket();
            nextRocket = 3000 + Math.random() * 4000;
        }
        rockets = rockets.filter(rocket => drawRocket(rocket, dt));
        drawTrail(dt);
        schedule();
    }

    function schedule() {
        if (!reduceMotion && visible && !document.hidden && !frameRequested) {
            frameRequested = true;
            requestAnimationFrame(draw);
        }
    }

    hero.addEventListener('pointermove', event => {
        if (reduceMotion) return;
        const rect = canvas.getBoundingClientRect();
        for (let i = 0; i < 2; i++) {
            trail.push({
                x: event.clientX - rect.left + (Math.random() - 0.5) * 16,
                y: event.clientY - rect.top + (Math.random() - 0.5) * 16,
                vx: (Math.random() - 0.5) * 0.02,
                vy: Math.random() * 0.015,
                size: Math.random() * 4 + 3,
                hue: 195 + Math.random() * 80,
                rotation: Math.random() * Math.PI,
                life: 1,
            });
        }
        if (trail.length > 350) trail.splice(0, trail.length - 350);
    });

    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => { resize(); if (reduceMotion) draw(performance.now()); }, 150);
    });
    new IntersectionObserver(entries => { visible = entries[0].isIntersecting; last = performance.now(); schedule(); }).observe(hero);
    document.addEventListener('visibilitychange', () => { last = performance.now(); schedule(); });

    resize();
    draw(performance.now());  // with reduced motion this is the only, static frame
})();
