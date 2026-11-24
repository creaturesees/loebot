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
  const res = await r.json();
  if (!res.ok) console.log(`Telegram ${method}: ${res.description}`);
  return res;
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

const GH_HEADERS = env => ({
  "Authorization": `Bearer ${env.GH_TOKEN}`,
  "Accept": "application/vnd.github+json",
  "X-GitHub-Api-Version": "2022-11-28",
  "User-Agent": "loe-schedule-watch",
});

const TARGETS = {
  both: "📢 Канал + 🤖 бот",
  channel: "📢 Тільки канал",
  bot: "🤖 Тільки бот",
  off: "⛔️ Вимкнено",
};

async function getVar(env, name) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/variables/${name}`, { headers: GH_HEADERS(env) });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GitHub ${r.status}: ${await r.text()}`);
  return (await r.json()).value;
}

async function setVar(env, name, value) {
  let r = await fetch(`https://api.github.com/repos/${REPO}/actions/variables/${name}`, {
    method: "PATCH", headers: GH_HEADERS(env), body: JSON.stringify({ name, value }),
  });
  if (r.status === 404) {
    r = await fetch(`https://api.github.com/repos/${REPO}/actions/variables`, {
      method: "POST", headers: GH_HEADERS(env), body: JSON.stringify({ name, value }),
    });
  }
  if (!r.ok) throw new Error(`GitHub ${r.status}: ${await r.text()}`);
}

async function tg(env, method, body) {
  const r = await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  return r.json();
}

async function panel(env) {
  const cur = (await getVar(env, "GPV_TARGET")) || "both";
  const channel = await getVar(env, "MAIN_CHANNEL_ID");
  const text = `<b>Куди надсилати графік ГПВ</b>\n\nЗараз: <b>${TARGETS[cur] || cur}</b>` +
    (channel ? `\nКанал: ${channel}` : "");
  const keyboard = Object.entries(TARGETS).map(([id, label]) => [{ text: (id === cur ? "✅ " : "") + label, callback_data: `gpv:${id}` }]);
  return { text, parse_mode: "HTML", reply_markup: { inline_keyboard: keyboard } };
}

async function onTelegram(update, env) {
  const msg = update.message;
  const cb = update.callback_query;
  const from = (msg || cb || {}).from || {};
  const owners = String(env.OWNER_ID || "").split(",").map(x => x.trim()).filter(Boolean);
  if (!owners.includes(String(from.id))) { console.log(`Ігнорую ${from.id}: немає в OWNER_ID`); return; }
  if (msg && /^\/(start|gpv|settings)\b/.test(msg.text || "")) {
    await tg(env, "sendMessage", { chat_id: msg.chat.id, ...(await panel(env)) });
  } else if (cb && /^gpv:(both|channel|bot|off)$/.test(cb.data || "")) {
    const value = cb.data.slice(4);
    try {
      await setVar(env, "GPV_TARGET", value);
      await tg(env, "answerCallbackQuery", { callback_query_id: cb.id, text: `Збережено: ${TARGETS[value]}` });
      await tg(env, "editMessageText", { chat_id: cb.message.chat.id, message_id: cb.message.message_id, ...(await panel(env)) });
    } catch (e) {
      await tg(env, "answerCallbackQuery", { callback_query_id: cb.id, text: "Помилка: " + e.message.slice(0, 150), show_alert: true });
    }
  }
}

async function dispatch(env) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: GH_HEADERS(env),
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
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/tg" && request.method === "POST") {
      if (!env.TG_SECRET || request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TG_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      const update = await request.json();
      ctx.waitUntil(onTelegram(update, env).catch(e => console.log("tg:", e.message)));
      return new Response("ok");
    }
    if (url.pathname === "/setup") {
      if (!env.TG_SECRET || url.searchParams.get("key") !== env.TG_SECRET) return new Response("forbidden", { status: 403 });
      const hook = await tg(env, "setWebhook", {
        url: `${url.origin}/tg`, secret_token: env.TG_SECRET, allowed_updates: ["message", "callback_query"],
      });
      const cmds = await tg(env, "setMyCommands", { commands: [{ command: "gpv", description: "куди надсилати графік ГПВ" }] });
      return new Response(JSON.stringify({ webhook: hook, commands: cmds }, null, 1), { headers: { "content-type": "application/json; charset=utf-8" } });
    }
    const snap = await snapshot().catch(e => ({ error: e.message }));
    return new Response(JSON.stringify({
      source: snap.source, items: snap.items, error: snap.error,
      lastTriggered: await env.STATE.get("triggered"),
    }, null, 1), { headers: { "content-type": "application/json; charset=utf-8" } });
  },
};
