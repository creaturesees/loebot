const API = "https://api.loe.lviv.ua/api/menu_items/";
const ITEM_IDS = ["238", "256"];
const MENU_API = "https://api.loe.lviv.ua/api/menus?page=1&type=photo-grafic";
const REPO = "creaturesees/loebot";
const WORKFLOW = "loe.yml";

async function getJson(url) {
  const r = await fetch(`${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}`, {
    headers: { "User-Agent": "Mozilla/5.0 (loe-schedule-watch)", "Accept": "application/json" },
    cf: { cacheTtl: 0 },
  });
  if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
  return r.json();
}

function pick(item) {
  return [item.name, item.rawHtml, item.rawMobileHtml, item.description, item.imageUrl].map(v => v || "").join("\u0001");
}

async function snapshot() {
  try {
    const items = await Promise.all(ITEM_IDS.map(id => getJson(API + id)));
    return { source: "menu_items", items: items.map(i => ({ name: i.name, len: (i.rawHtml || "").length })), text: items.map(pick).join("\u0002") };
  } catch (e) {
    const data = await getJson(MENU_API);
    const menu = Array.isArray(data) ? data[0] : (data["hydra:member"] || data.member || [])[0];
    const items = (menu && menu.menuItems || []).filter(i => !(i.children && i.children.length));
    return { source: "menus (" + e.message + ")", items: items.map(i => ({ name: i.name, len: (i.rawHtml || "").length })), text: items.map(pick).join("\u0002") };
  }
}

async function sha(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function dispatch(env) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GH_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "loe-schedule-watch",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  if (r.status !== 204) throw new Error(`GitHub → HTTP ${r.status} ${await r.text()}`);
}

async function check(env) {
  const snap = await snapshot();
  const hash = await sha(snap.text);
  const last = await env.STATE.get("hash");
  if (hash === last) return { changed: false, ...snap, hash };
  await dispatch(env);
  await env.STATE.put("hash", hash);
  await env.STATE.put("triggered", new Date().toISOString());
  return { changed: true, ...snap, hash };
}

export default {
  async scheduled(event, env, ctx) {
    const res = await check(env);
    console.log(res.changed ? "Графік змінився, запущено бота" : "Без змін", res.source);
  },
  async fetch(request, env) {
    const snap = await snapshot().catch(e => ({ error: e.message }));
    return new Response(JSON.stringify({
      source: snap.source, items: snap.items, error: snap.error,
      lastTriggered: await env.STATE.get("triggered"),
    }, null, 1), { headers: { "content-type": "application/json; charset=utf-8" } });
  },
};
