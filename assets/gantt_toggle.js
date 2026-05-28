window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.gantt = {
    toggle: function (nClicks, expanded) {
        if (!window.dash_clientside.callback_context) {
            return window.dash_clientside.no_update;
        }
        var ctx = window.dash_clientside.callback_context;
        if (!ctx.triggered || !ctx.triggered.length) {
            return window.dash_clientside.no_update;
        }

        var id  = JSON.parse(ctx.triggered[0].prop_id.replace('.n_clicks', ''));
        var key = id.index; // "dev:safe_dev", "func:safe_fk", "spr:safe_ip", "item:wid"

        var expandedSprs  = (expanded && expanded.s) ? expanded.s.slice() : [];
        var expandedItems = (expanded && expanded.t) ? expanded.t.slice() : [];

        if (key.slice(0, 4) === 'dev:') {
            var devKey   = key.slice(4);
            var isDevExp = expandedSprs.indexOf(devKey) !== -1;
            if (isDevExp) {
                expandedSprs = expandedSprs.filter(function (s) { return s !== devKey; });
            } else {
                expandedSprs.push(devKey);
            }
            var willExpDev = !isDevExp;
            var devEl  = document.getElementById('gantt-si-dev-' + devKey);
            if (devEl) devEl.style.display = willExpDev ? 'block' : 'none';
            var devBtnId = '{"index":"dev:' + devKey + '","type":"gantt-toggle"}';
            var devBtnEl = document.getElementById(devBtnId);
            if (devBtnEl) devBtnEl.textContent = willExpDev ? '▼' : '►';

        } else if (key.slice(0, 5) === 'func:') {
            var funcKey   = key.slice(5);
            var isFuncExp = expandedItems.indexOf(funcKey) !== -1;
            if (isFuncExp) {
                expandedItems = expandedItems.filter(function (t) { return t !== funcKey; });
            } else {
                expandedItems.push(funcKey);
            }
            var willExpFunc = !isFuncExp;
            var funcEl  = document.getElementById('gantt-it-func-' + funcKey);
            if (funcEl) funcEl.style.display = willExpFunc ? 'block' : 'none';
            var funcBtnId = '{"index":"func:' + funcKey + '","type":"gantt-toggle"}';
            var funcBtnEl = document.getElementById(funcBtnId);
            if (funcBtnEl) funcBtnEl.textContent = willExpFunc ? '▼' : '►';

        } else if (key.slice(0, 4) === 'spr:') {
            var sprKey   = key.slice(4);
            var isSprExp = expandedSprs.indexOf(sprKey) !== -1;
            if (isSprExp) {
                expandedSprs = expandedSprs.filter(function (s) { return s !== sprKey; });
            } else {
                expandedSprs.push(sprKey);
            }
            var willExpSpr = !isSprExp;
            var sprEl  = document.getElementById('gantt-si-' + sprKey);
            if (sprEl) sprEl.style.display = willExpSpr ? 'block' : 'none';
            var sprBtnId = '{"index":"spr:' + sprKey + '","type":"gantt-toggle"}';
            var sprBtnEl = document.getElementById(sprBtnId);
            if (sprBtnEl) sprBtnEl.textContent = willExpSpr ? '▼' : '►';

        } else if (key.slice(0, 5) === 'item:') {
            var itemKey   = key.slice(5);
            var isItemExp = expandedItems.indexOf(itemKey) !== -1;
            if (isItemExp) {
                expandedItems = expandedItems.filter(function (t) { return t !== itemKey; });
            } else {
                expandedItems.push(itemKey);
            }
            var willExpItem = !isItemExp;
            var itemEl  = document.getElementById('gantt-it-' + itemKey);
            if (itemEl) itemEl.style.display = willExpItem ? 'block' : 'none';
            var itemBtnId = '{"index":"item:' + itemKey + '","type":"gantt-toggle"}';
            var itemBtnEl = document.getElementById(itemBtnId);
            if (itemBtnEl) itemBtnEl.textContent = willExpItem ? '▼' : '►';
        }

        return { s: expandedSprs, t: expandedItems };
    }
};
