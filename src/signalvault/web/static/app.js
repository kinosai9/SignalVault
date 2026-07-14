/* SignalVault — shared frontend scripts. */

// ── Mobile nav toggle ──────────────────────────────────────────────────
(function () {
    var button = document.querySelector('[data-nav-toggle]');
    var body = document.body;
    if (!button) return;

    function setOpen(open) {
        body.classList.toggle('nav-open', open);
        button.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    button.addEventListener('click', function () {
        setOpen(!body.classList.contains('nav-open'));
    });

    var closeTarget = document.querySelector('[data-nav-close]');
    if (closeTarget) {
        closeTarget.addEventListener('click', function () { setOpen(false); });
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') setOpen(false);
    });

    document.querySelectorAll('.app-sidebar a').forEach(function (link) {
        link.addEventListener('click', function () { setOpen(false); });
    });
})();

// ── Page load timing ───────────────────────────────────────────────────
(function () {
    if (!window.performance || !performance.timing) return;
    window.addEventListener('load', function () {
        setTimeout(function () {
            var t = performance.timing;
            var dns      = t.domainLookupEnd - t.domainLookupStart;
            var connect  = t.connectEnd - t.connectStart;
            var ttfb     = t.responseStart - t.requestStart;
            var domReady = t.domContentLoadedEventEnd - t.requestStart;
            var pageLoad = t.loadEventEnd - t.requestStart;
            console.log('[PageTiming] DNS:' + dns + 'ms TCP:' + connect + 'ms TTFB:' + ttfb + 'ms DOMReady:' + domReady + 'ms PageLoad:' + pageLoad + 'ms');
        }, 0);
    });
})();

// ── Job status polling (used by task_detail.html) ──────────────────────
function startJobPolling(jobId, jobType) {
    var maxPollSeconds = jobType === 'sync' ? 120 : 900;
    var pollInterval = 2000;
    var startTime = Date.now();

    function poll() {
        var elapsed = (Date.now() - startTime) / 1000;
        if (elapsed > maxPollSeconds) {
            document.getElementById('progress-msg').textContent = '任务执行时间较长，请稍后刷新页面查看结果。';
            return;
        }
        fetch('/tasks/' + jobId + '/status')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.finished) {
                    if (data.status === 'success') {
                        document.getElementById('progress-bar').style.width = '100%';
                        document.getElementById('progress-msg').textContent = '完成';
                        if (data.report_id) {
                            window.location.href = '/reports/' + data.report_id;
                        } else {
                            setTimeout(function () { location.reload(); }, 2000);
                        }
                    } else {
                        document.getElementById('progress-msg').textContent = '失败: ' + (data.error_summary || '未知错误');
                        document.getElementById('progress-bar').className = 'progress-fill progress-failed';
                    }
                    return;
                }
                var pct = data.progress_pct || 0;
                document.getElementById('progress-bar').style.width = pct + '%';
                var stageMsg = data.stage_message || data.stage || '';
                document.getElementById('progress-msg').textContent = stageMsg;
                var elapsedDisplay = data.elapsed_display || '';
                if (elapsedDisplay) {
                    var el = document.getElementById('elapsed-display');
                    if (el) el.textContent = elapsedDisplay;
                }
                setTimeout(poll, pollInterval);
            })
            .catch(function () {
                setTimeout(poll, pollInterval);
            });
    }
    poll();
}
