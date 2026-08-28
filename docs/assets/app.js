const PAGE = 20;
let ranks = [];
let view = [];
let page = 1;
let loaded = false;
let searchTimer = 0;
let lastDaily = [];
const SAMPLE_HINT = 36;

function fmt(n) {
  return Number(n).toLocaleString("zh-CN");
}

function rowOf(a) {
  return { r: a[0], n: a[1], id: a[2], c: a[3], lk: a[4], s: a[5] || "" };
}

function hue(id) {
  return (Math.abs(Number(id) || 0) * 47) % 360;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function avHtml(u) {
  const ch = (u.n || "?").slice(0, 1);
  return `<span class="av" style="background:hsl(${hue(u.id)} 42% 62%)">${escapeHtml(ch)}</span>`;
}

function medal(r) {
  if (r === 1) return `<span class="medal m1">1</span>`;
  if (r === 2) return `<span class="medal m2">2</span>`;
  if (r === 3) return `<span class="medal m3">3</span>`;
  return `<span class="rank-n">${r}</span>`;
}

async function load() {
  const [ov, daily] = await Promise.all([
    fetch("./data/overview.json").then((r) => r.json()),
    fetch("./data/daily.json").then((r) => r.json()),
  ]);
  lastDaily = daily;
  document.getElementById("note").textContent = ov.note;
  document.getElementById("video").href = ov.video;
  document.getElementById("stats").innerHTML = [
    ["B站显示", fmt(ov.official)],
    ["已入库", fmt(ov.stored)],
    ["覆盖率", ov.cover + "%"],
    ["用户数", fmt(ov.users)],
    ["时间窗", ov.window.split(" ~ ")[0].slice(0, 10) + " 起"],
    ["导出", (ov.exported || "").slice(0, 10)],
  ]
    .map(([k, v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`)
    .join("");
  drawMonthChart(daily);

  const files = ov.files || ["rank.json"];
  document.getElementById("shown").textContent = "正在载入榜单…";
  for (let i = 0; i < files.length; i++) {
    const part = await fetch("./data/" + files[i]).then((r) => r.json());
    for (const a of part) ranks.push(rowOf(a));
    if (i === 0) {
      renderPodium();
      view = ranks;
      render();
    }
    document.getElementById("shown").textContent =
      "已载入 " + fmt(ranks.length) + " / " + fmt(ov.rank_shown);
  }
  view = filterNow(document.getElementById("q").value);
  loaded = true;
  document.getElementById("shown").textContent =
    "共 " + fmt(ranks.length) + " 人 · 样例截断 " + SAMPLE_HINT + " 字 · " + ov.exported;
  render();
}

function renderPodium() {
  const top = ranks.slice(0, 3);
    const labels = ["第 1 名", "第 2 名", "第 3 名"];
  document.getElementById("podium").innerHTML = top
    .map(
      (u, i) => `<article class="card m${i + 1}">
      <div class="place">${labels[i]}</div>
      <div class="name">${escapeHtml(u.n)}</div>
      <a class="uid" href="https://space.bilibili.com/${u.id}" target="_blank" rel="noopener">UID ${u.id}</a>
      <div class="nums">
        <div><b>${fmt(u.c)}</b><span>评论</span></div>
        <div><b>${fmt(u.lk)}</b><span>点赞</span></div>
      </div>
      <div class="quote">${u.s ? "「" + escapeHtml(u.s) + "」" : ""}</div>
    </article>`
    )
    .join("");
}

function byMonth(daily) {
  const m = new Map();
  for (const x of daily) {
    const k = x.d.slice(0, 7);
    m.set(k, (m.get(k) || 0) + x.c);
  }
  return [...m.entries()].map(([d, c]) => ({ d, c }));
}

function drawMonthChart(daily) {
  const months = byMonth(daily);
  const canvas = document.getElementById("chart");
  const tip = document.getElementById("tip");
  const box = canvas.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const cssW = box.clientWidth || 960;
  const cssH = 240;
  canvas.width = Math.floor(cssW * dpr);
  canvas.height = Math.floor(cssH * dpr);
  canvas.style.width = cssW + "px";
  canvas.style.height = cssH + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  if (!months.length) return;

  const pad = { l: 48, r: 12, t: 16, b: 36 };
  const max = Math.max(...months.map((x) => x.c)) || 1;
  const n = months.length;
  const gw = cssW - pad.l - pad.r;
  const gh = cssH - pad.t - pad.b;
  const bw = gw / n;

  ctx.strokeStyle = "#27343c";
  ctx.beginPath();
  ctx.moveTo(pad.l, pad.t);
  ctx.lineTo(pad.l, pad.t + gh);
  ctx.lineTo(pad.l + gw, pad.t + gh);
  ctx.stroke();

  ctx.fillStyle = "#8b9aa3";
  ctx.font = "11px sans-serif";
  ctx.textAlign = "right";
  for (const t of [0, 0.5, 1]) {
    const y = pad.t + gh - t * gh;
    const label = t === 0 ? "0" : t === 1 ? fmt(max) : "";
    if (label) ctx.fillText(label, pad.l - 6, y + 4);
  }

  months.forEach((x, i) => {
    const h = (x.c / max) * gh;
    const x0 = pad.l + i * bw + bw * 0.18;
    const y0 = pad.t + gh - h;
    ctx.fillStyle = x.d === "2026-02" ? "#e2c27a" : "#4eb3c2";
    ctx.fillRect(x0, y0, bw * 0.64, Math.max(h, 1));
  });

  ctx.fillStyle = "#8b9aa3";
  ctx.textAlign = "center";
  let lastY = "";
  months.forEach((x, i) => {
    const y = x.d.slice(0, 4);
    if (y !== lastY) {
      ctx.fillText(y, pad.l + i * bw + bw / 2, cssH - 12);
      lastY = y;
    }
  });

  canvas.onmousemove = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const x = ev.clientX - rect.left;
    const i = Math.floor((x - pad.l) / bw);
    if (i < 0 || i >= n) {
      tip.hidden = true;
      return;
    }
    const item = months[i];
    tip.hidden = false;
    tip.textContent = item.d + "  " + fmt(item.c) + " 条";
    tip.style.left = Math.min(rect.width - 140, Math.max(8, x + 10)) + "px";
    tip.style.top = "12px";
  };
  canvas.onmouseleave = () => {
    tip.hidden = true;
  };

  const peak = months.reduce((a, b) => (a.c > b.c ? a : b));
  document.getElementById("chartHint").textContent =
    "按月。" +
    peak.d +
    " 最高（" +
    fmt(peak.c) +
    " 条）。2026-02 是新宣传片出来之后涌进来的，不是图坏了。";
}

function render() {
  const start = (page - 1) * PAGE;
  const rows = view.slice(start, start + PAGE);
  const maxC = view[0] ? view[0].c : 1;
  const tb = document.getElementById("tbody");
  tb.innerHTML = rows
    .map((u) => {
      const w = Math.max(4, Math.round((u.c / maxC) * 100));
      const top = u.r <= 3 ? ` class="top${u.r}"` : "";
      return `<tr${top}>
      <td class="col-rank">${medal(u.r)}</td>
      <td>
        <div class="user">
          ${avHtml(u)}
          <div>
            <div class="uname">${escapeHtml(u.n)}</div>
            <a class="uid" href="https://space.bilibili.com/${u.id}" target="_blank" rel="noopener">UID ${u.id}</a>
          </div>
        </div>
      </td>
      <td class="col-num">${fmt(u.c)}<div class="bar"><i style="width:${w}%"></i></div></td>
      <td class="col-num">${fmt(u.lk)}</td>
      <td class="sample">${escapeHtml(u.s)}</td>
    </tr>`;
    })
    .join("");

  const pages = Math.max(1, Math.ceil(view.length / PAGE));
  if (page > pages) page = pages;
  const from = view.length ? start + 1 : 0;
  const to = Math.min(start + PAGE, view.length);
  const pg = document.getElementById("pager");
  const btns = [];
  const add = (i, label) => {
    btns.push(`<button class="${i === page ? "on" : ""}" data-p="${i}">${label}</button>`);
  };
  add(1, "1");
  if (page > 3) btns.push("<span>…</span>");
  for (let i = Math.max(2, page - 2); i <= Math.min(pages - 1, page + 2); i++) add(i, String(i));
  if (page < pages - 2) btns.push("<span>…</span>");
  if (pages > 1) add(pages, String(pages));
  pg.innerHTML =
    btns.join("") +
    `<label class="jump">跳转 <input id="jump" type="number" min="1" max="${pages}" value="${page}"></label>` +
    `<span class="count">${fmt(from)}–${fmt(to)} / ${fmt(view.length)}</span>`;
  pg.onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    page = Number(b.dataset.p);
    render();
  };
  const jump = document.getElementById("jump");
  if (jump) {
    jump.onchange = () => {
      page = Math.min(pages, Math.max(1, Number(jump.value) || 1));
      render();
    };
  }
}

function filterNow(raw) {
  const q = raw.trim().toLowerCase();
  if (!q) return ranks;
  return ranks.filter((u) => u.n.toLowerCase().includes(q) || String(u.id).includes(q));
}

document.getElementById("q").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    page = 1;
    view = filterNow(e.target.value);
    render();
  }, loaded ? 180 : 0);
});

window.addEventListener("resize", () => {
  if (lastDaily.length) drawMonthChart(lastDaily);
});

load().catch((err) => {
  document.getElementById("note").textContent = "数据加载失败：" + err;
});
