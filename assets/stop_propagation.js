/**
 * Prevents VSTS / ADO link clicks (class="ado-vsts-link") from bubbling up to
 * the parent table row's React onClick handler (which would open the side panel).
 * The link navigation (href / target="_blank") is unaffected because stopPropagation
 * does not prevent the browser's default action.
 *
 * Strategy: attach a native bubble-phase listener to the <tr> ancestor of each link.
 * Native tr listeners fire before React's root-level delegated handler, so stopping
 * propagation here prevents Dash from incrementing the row's n_clicks.
 */
(function () {
    function attachToTr(tr) {
        if (tr._adoLinkStop) return;
        tr._adoLinkStop = true;
        tr.addEventListener('click', function (e) {
            if (e.target && e.target.closest && e.target.closest('a.ado-vsts-link')) {
                e.stopPropagation();
            }
        });
    }

    function scan(root) {
        if (!root || !root.querySelectorAll) return;
        root.querySelectorAll('a.ado-vsts-link').forEach(function (link) {
            var tr = link.closest('tr');
            if (tr) attachToTr(tr);
        });
    }

    var observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (m) {
            m.addedNodes.forEach(function (node) {
                if (node.nodeType !== 1) return;
                if (node.tagName === 'TR') {
                    if (node.querySelector('a.ado-vsts-link')) attachToTr(node);
                } else {
                    scan(node);
                }
            });
        });
    });

    function init() {
        scan(document.body);
        observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
